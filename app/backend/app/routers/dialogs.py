import json
import logging
import re
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import realtime
from app.core.config import get_settings
from app.db import get_db
from app.deps import ensure_space_access, get_current_user
from app.llm.base import Message, ToolCall
from app.llm.factory import get_llm_client
from app.models import AssistantMemory, Item, Space, SpaceMember, User
from app.routers.items import create_item_row
from app.schemas.dialog import DialogCreate, DialogOut, DialogSummaryOut, MessageCreate
from app.tools.registry import ToolContext, dispatch, get_tool_definitions

router = APIRouter(prefix="/api/dialogs", tags=["dialogs"])
logger = logging.getLogger(__name__)

# Предохранитель от зацикливания агента: LLM может звать инструменты сколько
# угодно раз внутри одного хода, но не бесконечно — на такой глубине что-то
# явно пошло не так, лучше вернуть частичный результат, чем платить за LLM
# без остановки.
MAX_TOOL_ITERATIONS = 8

SYSTEM_PROMPT_BASE = (
    "Ты — ассистент базы знаний Notenotes. Ты работаешь внутри диалога с "
    "пользователем и можешь искать и изменять его заметки и списки через "
    "доступные инструменты. Отвечай на языке пользователя (по умолчанию — "
    "русский). Список инструментов, которые тебе реально доступны на этот "
    "ход, — только то, что передано в tools; ниже в инструкциях могут "
    "упоминаться и другие тулы, но если конкретно сейчас его нет в tools "
    "(например, пользователь отключил его в настройках) — не пытайся его "
    "вызвать, прямо скажи, что не можешь это сделать сейчас.\n\n"
    "Отвечай КОРОТКО. Пользователь читает это в чате, не в документе. "
    "Обычный ответ — 1-3 предложения. Не добавляй разделы вроде «Что "
    "дальше?», «Варианты действий», списки идей и предложений, если тебя "
    "об этом не просили явно — для выбора следующего шага используй "
    "suggest_replies (коротко), а не абзацы текста. Не пересказывай, что "
    "ты только что сделал, развёрнуто — одной фразы достаточно («Готово, "
    "заметка создана»). Если пользователь просит подробностей — тогда "
    "разворачивайся, но по умолчанию будь лаконичен.\n\n"
    "У каждого твоего ответа есть кнопка «Скопировать», которая копирует "
    "ВЕСЬ текст сообщения целиком, как есть. Если пользователь просит "
    "составить текст для отправки/вставки куда-то (письмо, сообщение, пост) "
    "— пиши ТОЛЬКО этот текст, без вступления вроде «Вот текст письма:» и "
    "без комментариев после, иначе они попадут в буфер обмена вместе с "
    "текстом. Комментарий или уточняющий вопрос — только отдельным сообщением "
    "до или после, не внутри того же ответа.\n\n"
    "Никогда не выдумывай факты — ни содержимое заметки/списка, ни то, что "
    "нашлось (или не нашлось) в вебе. list_folders, list_items_in_folder и "
    "list_all_items дают только название/id объектов, не их реальное "
    "содержимое; search_base даёт только обрезанный отрывок (300 символов "
    "для заметки) — НЕ полное содержимое. Прежде чем показать пользователю "
    "содержимое заметки или списка, отвечать по нему или считать, что там "
    "чего-то нет — сначала получи настоящие данные целиком (get_list — для "
    "списка, get_note — для заметки). Если данных нет или получить их не "
    "удалось — так и скажи, не сочиняй правдоподобный ответ. Никогда не "
    "изобретай инструмент, которого нет в списке доступных — если "
    "подходящего тула нет, так и скажи, не пытайся вызвать несуществующий. "
    "Точно так же нельзя утверждать, что сделал что-то, для чего не вызвал "
    "нужный тул — например, если пользователь просил папку и заметку, а ты "
    "вызвал только create_note без folder_id, папка НЕ создана, даже если "
    "план из предыдущего сообщения её упоминал; отчитывайся только по "
    "тому, что реально подтвердил результат тула, а не по тому, что "
    "собирался сделать.\n\n"
    "search_base ищет по буквальным словам и не понимает синонимы или "
    "однокоренные приставочные формы (например, 'купить', 'покупка' и "
    "'закупка' для него — разные слова, хотя по смыслу связаны). Если "
    "search_base ничего не нашёл, а объект правдоподобно должен быть в "
    "базе — прежде чем говорить «не нашёл», вызови list_all_items и "
    "просмотри заголовки сам: ты понимаешь смысл лучше текстового поиска. "
    "Название, которое называет пользователь, может быть не названием "
    "заметки/списка, а названием ПАПКИ (бытовое именование места, например "
    "«Холодильник» для папки с продуктовыми списками) — если поиск по "
    "заметкам/спискам ничего не даёт, обязательно проверь list_folders на "
    "совпадение по названию папки и, если нашлось, посмотри её содержимое "
    "через list_items_in_folder, прежде чем сообщать, что ничего нет.\n\n"
    "Никогда не составляй и не достраивай URL сам, если он не пришёл "
    "буквально из результата инструмента (особенно ссылки на Google Maps с "
    "координатами/place-id — их без реального источника не существует, ты "
    "их гарантированно придумаешь неверными).\n\n"
    "Когда пользователь ссылается на папку или заметку неточно (своими "
    "словами, а не точным названием) — не угадывай молча. Найди похожие "
    "варианты (list_folders/search_base) и явно подтверди с пользователем, "
    "что ты понял правильно, прежде чем действовать. Если понимание "
    "подтвердилось и оно не очевидно из названия — сохрани его через "
    "remember_fact, чтобы не переспрашивать в следующий раз (сначала "
    "проверь list_memories, нет ли уже такого факта).\n\n"
    "remember_fact не ограничен только папками/заметками — используй его "
    "шире, для любого факта о пользователе, который пригодится в БУДУЩИХ "
    "разговорах, не только в этом: пользователь прямо просит запомнить "
    "что-то ('запомни, что...', 'не забудь, что...'); пользователь называет "
    "durable-факт о себе (постоянные предпочтения, важные даты, личные "
    "обозначения вроде 'холодильник значит список продуктов'); пользователь "
    "поправляет тебя по существу, а не один раз. НЕ сохраняй то, что и так "
    "уже лежит в заметках/списках (для этого есть сама база) и разовые "
    "детали одного вопроса, которые не пригодятся заново. Сначала проверь "
    "list_memories, чтобы не задублировать.\n\n"
    "Перед тем как создавать что-то новое по теме — проверь search_base "
    "(по заметкам) и, если речь о конкретной папке, list_items_in_folder "
    "(по её содержимому), а не предполагай вслепую, что там есть или нет. "
    "Если папка пуста — не молчи об этом: предложи пользователю конкретный "
    "следующий шаг (например, какую заметку или список стоит завести) и "
    "уточни детали, а не только перечисляй вопросы одним блоком.\n\n"
    "Для отмечаемых пунктов (покупки, задачи, чек-листы) создавай список "
    "(create_list), а не заметку с текстом-имитацией списка — в списке "
    "пункты можно по-настоящему отмечать выполненными. Чтобы посмотреть "
    "реальные пункты — get_list. Чтобы отметить УЖЕ существующий пункт "
    "выполненным/купленным — toggle_list_entry, а не add_list_entry: "
    "add_list_entry создаёт новый пункт и превратит отметку в дублирование.\n\n"
    "Когда у твоего вопроса есть естественные короткие варианты ответа "
    "(выбор из существующих папок, да/нет, чек-лист или заметка) — заканчивай "
    "ход ВЫЗОВОМ ИНСТРУМЕНТА suggest_replies с 2-5 вариантами, чтобы "
    "пользователь мог кликнуть, а не печатать текстом. Никогда не пиши "
    "варианты просто текстом в духе «Варианты действий (можно выбрать "
    "кликом): 1. ... 2. ...» — если сам не вызвал suggest_replies, ничего "
    "кликабельного не появится и пользователь увидит нерабочий текст. Либо "
    "вызови инструмент, либо не упоминай про клик вообще. Если ожидается "
    "свободный текст — не вызывай suggest_replies.\n\n"
    "Удаление заметки перемещает её в корзину, не безвозвратно, но вызывай "
    "его только когда пользователь действительно просит удалить. Содержимое "
    "заметок пиши в формате Markdown."
)

# Не настоящий тул (нет ToolDefinition/handler — модели нечего вызывать),
# а переключаемое ПОВЕДЕНИЕ поверх get_note/search_base, которые и так
# отдают контент целиком. Раньше жило безусловно в SYSTEM_PROMPT_BASE и не
# отображалось в «Умениях ассистента» — с точки зрения пользователя это
# несогласованность с остальными скиллами (web_search, calendar и т.п.),
# у которых есть явный переключатель. Гейтится так же, как
# TOOL_PROMPT_FRAGMENTS, но по сырому disabled_tools, а не enabled_tools
# (последний собран из реальных ToolDefinition и никогда не будет
# содержать имя без тула — см. SKILL_CATALOG/list_skills в tools/registry.py).
SHOW_NOTE_IMAGES_SKILL = "show_note_images"
SHOW_NOTE_IMAGES_PROMPT_FRAGMENT = (
    "Если через get_note/search_base нашлась заметка с картинкой (она в "
    "содержимом как markdown ![]() или как HTML <img src=\"...\">) и картинка "
    "по смыслу отвечает на вопрос пользователя — покажи её прямо в своём "
    "ответе, но ТОЛЬКО в markdown-синтаксисе ![подпись](URL) с тем же URL, "
    "что был в содержимом; если исходно был <img>-тег, преобразуй его в эту "
    "же markdown-форму сам — как есть, HTML-тег в чате не отрисуется. Не "
    "вставляй картинку, если пользователь просто упомянул заметку мимоходом "
    "или картинка не по теме вопроса — не в каждом ответе, где есть заметка "
    "с картинкой, нужно её показывать.\n\n"
    "Если запрос подразумевает НЕСКОЛЬКО картинок сразу (например 'покажи "
    "все фото X', 'какие есть картинки про Y') — не ограничивайся одной "
    "самой релевантной, вставь ![]() на каждую подходящую (фронт сам "
    "соберёт их в галерею, если картинок больше одной). Если подходящих "
    "картинок больше 10 — вставь только первые 10, прямо скажи в тексте "
    "ответа, что нашлось больше, и вызови suggest_replies с вариантом "
    "вроде 'Показать ещё 10', чтобы пользователь мог продолжить просмотр."
)

# Инструкции про конкретные необязательные тулы — добавляются в промпт,
# только если тул реально доступен на этот ход (не отключён в настройках
# пользователя). Раньше эти абзацы жили в SYSTEM_PROMPT_BASE безусловно —
# из-за этого модель пыталась звать run_python даже отключённым: промпт
# говорил "используй run_python", а тула не было в tools, и модель всё
# равно сформировала вызов с угаданной (неверной) схемой аргументов вместо
# честного "не могу". Условность здесь — не косметика, а реальный фикс.
TOOL_PROMPT_FRAGMENTS: dict[str, str] = {
    "search_base": (
        "Если запрос про ОБЩУЮ ТЕМУ, а не точную фразу (например «найди "
        "заметки про больницы», а не «найди заметку с названием X») — "
        "СНАЧАЛА проверь list_tags: если есть тег по теме (например "
        "«здоровье» для темы про больницы), используй list_items_by_tag "
        "— пользователь мог заранее разложить заметки по тегам, и это "
        "надёжнее угадывания формулировок. Реальный случай: search_base "
        "тремя параллельными запросами-вариациями («медицина Польша», "
        "«клиника», «врач») не нашёл нужную заметку и вместо этого зацепил "
        "случайным совпадением слова совершенно постороннюю (билет на "
        "самолёт, где в OCR-описании упомянута страна) — а под тегом "
        "«здоровье» нужная заметка уже лежала. НЕ пытайся заменить один "
        "непонятный запрос россыпью из 3+ параллельных вариаций "
        "search_base на разные словоформы — это увеличивает шанс "
        "случайного мусорного совпадения, а не качество результата; "
        "если после тегов и одного-двух формулировок search_base всё "
        "ещё пусто — переходи к list_all_items и оцени заголовки сам, "
        "а не продолжай штурмовать search_base новыми вариациями.\n\n"
        "ВАЖНО: карточки на фронте (билет, кнопка «Открыть заметку», "
        "карточки сайтов-ссылок) рисуются ТОЛЬКО по вызову get_note, "
        "НЕ по search_base — у search_base по своей природе бывают "
        "случайные/нерелевантные совпадения (широкий OR-поиск), и "
        "рисовать по нему карточку означало бы показывать то, что ты сам "
        "мог посчитать нерелевантным и не упомянуть в ответе. Поэтому: "
        "search_base — только чтобы найти id подходящей заметки; если "
        "по итогу решил показать/сослаться на конкретную заметку в "
        "ответе — вызови get_note(item_id=...) на неё в ЭТОМ ЖЕ ходу, "
        "даже если её content ты уже видел в результате search_base. Без "
        "этого лишнего вызова карточка не появится.\n\n"
        "Если get_note вернул заметку с material_type=\"ticket\" "
        "(билет — жд/авиа/на мероприятие) — в её properties уже готовые "
        "чистые поля (ticket_type, datetime_start/end, location_from/to, "
        "seat), используй их напрямую для ответа, не пытайся разобрать "
        "content (там только служебная HTML-разметка карточки, не текст). "
        "Фронтенд сам отрисует красивую карточку билета под твоим ответом "
        "— НЕ переписывай все поля билета текстом заново (дублирование), "
        "достаточно коротко ответить на сам вопрос (например «да, у тебя "
        "есть рейс во Франкфурт 26 марта, место 21A» — не расписывать "
        "терминал/группу посадки и т.п., если не спросили конкретно).\n\n"
        "На ЛЮБУЮ заметку/список, полученные через get_note (не только "
        "билеты), фронтенд САМ рисует под твоим ответом кнопку "
        "«Открыть «название»»» — она открывает заметку прямо в приложении. "
        "Значит: (1) НЕ пытайся сам сформировать или вставить ссылку на "
        "заметку в текст — прямых URL на внутренние объекты не существует, "
        "любая такая ссылка в твоём тексте всё равно будет вырезана; "
        "(2) НЕ говори пользователю, что не можешь дать ссылку на заметку "
        "— можешь, просто упомяни её название/о чём она, кнопка появится "
        "сама; (3) если пользователь прямо просит именно ссылку/переход на "
        "заметку — не пытайся объяснить словами, где её искать, кнопка уже "
        "решает эту задачу, достаточно короткого ответа по сути вопроса; "
        "(4) кнопка привязана к вызову get_note именно в ЭТОМ твоём "
        "ответе — если id заметки уже известен из предыдущих реплик этого "
        "диалога, но в текущем ходу ты не вызвал get_note заново, кнопка "
        "не появится.\n\n"
        "Если в content заметки есть <a href=\"...\" data-linkpreview></a> "
        "(сохранённые ссылки на внешние сайты — например, пользователь "
        "переслал ссылку в Telegram) — фронтенд САМ рисует под твоим "
        "ответом для каждой такой ссылки карточку сайта (favicon + "
        "заголовок страницы, кликабельно), в точности как в самом "
        "редакторе заметок. Значит: НЕ пытайся перечислять эти ссылки "
        "текстом (названия товаров/страниц и т.п.) — просто коротко "
        "ответь по сути вопроса, карточки появятся сами под ответом.\n\n"
        "ВАЖНОЕ ПРАВИЛО, общее для всех карточек (билет, заметка, ссылки "
        "внутри неё): они появляются, ТОЛЬКО если get_note был вызван "
        "именно в этом твоём ответе — не в одном из предыдущих ходов "
        "диалога и не через search_base. Если пользователь просит "
        "показать/прислать/повторить заметку, ссылки или билет, о которых "
        "уже шла речь раньше в этом диалоге — ты ОБЯЗАН вызвать "
        "get_note(item_id=...) заново прямо сейчас, даже если сам факт и "
        "содержимое заметки тебе и так известны из контекста. Один лишний "
        "вызов тула дешевле, чем ответ без единой работающей ссылки — "
        "если сомневаешься, вызывай тул."
    ),
    "run_python": (
        "Для точных вычислений (суммы, проценты, разница дат, сортировка "
        "чисел, агрегация данных из заметки/списка) — используй run_python, "
        "а не считай в уме: языковые модели систематически ошибаются в "
        "арифметике, а тул считает точно. Не показывай пользователю код, "
        "если не просил — только результат."
    ),
    "web_search": (
        "Если пользователь спрашивает про конкретное название реального "
        "места/заведения/бренда, а не то, что он мог сам записать в "
        "заметки, — не зацикливайся на внутреннем поиске: сразу попробуй "
        "web_search по этому названию напрямую, это вопрос про реальный "
        "мир, а не про базу заметок пользователя. Используй его экономно "
        "— только если ответа точно нет в базе пользователя.\n\n"
        "Формулируя запрос про реальное место в другой стране — не "
        "используй только язык разговора с пользователем. Источников о "
        "конкретном городе на местном языке почти всегда на порядок "
        "больше, чем на русском (например, про Познань в Польше — "
        "по-польски, про Берлин — по-немецки или по-английски). Делай хотя "
        "бы один из запросов (можно параллельно, за один вызов можно "
        "запросить сразу несколько web_search) на языке страны/города, о "
        "котором речь.\n\n"
        "Используй только то, что БУКВАЛЬНО есть в content результата — не "
        "досочиняй. Если нужна ссылка на место — бери url прямо из "
        "результата поиска как есть, не переделывая. Не связывай "
        "результаты разных запросов друг с другом по совпадению названия "
        "— если результат явно о другом городе/стране (например, ресторан "
        "в Алматы при вопросе про Познань), это не тот же объект, даже "
        "если название похоже. Если результаты не дают точного ответа — "
        "прямо скажи, что нашёл только частично, и предложи пользователю "
        "проверить по ссылке самому. depth=basic по умолчанию — если "
        "результаты оказались общими listicle-страницами без конкретного "
        "ответа, ИЛИ если пользователь просил НЕСКОЛЬКО вариантов, а после "
        "отсева нерелевантного осталось меньше 4-5 подходящих — попробуй "
        "тот же запрос ещё раз с depth=advanced (в пределах лимита вызовов "
        "на ход), прежде чем сдаваться с неполным списком. Если и после "
        "этого результат неполный — предложи suggest_replies с вариантом "
        "«Поискать глубже»."
    ),
    "create_calendar_event": (
        "Когда пользователь просит создать заметку/напоминание о конкретном "
        "будущем событии с известной датой (и желательно временем) — после "
        "создания заметки вызови create_calendar_event с теми же title/датой. "
        "Своей интеграции с календарём нет, но этот тул даёт пользователю "
        "кнопку «Добавить в календарь» — в один клик открывает системный "
        "диалог добавления события в Google/Apple/Outlook. Дату для start "
        "бери только из того, что явно сказал пользователь (или что "
        "нашлось в web_search как факт), — если дата не названа, сначала "
        "спроси, не угадывай. Кнопка появляется сама по результату этого "
        "тула — никогда не пиши вторую ссылку на добавление в календарь сам "
        "текстом (например, calendar.google.com/render с руками собранными "
        "параметрами): она не проверена и придумана, а кнопка от тула уже "
        "делает то же самое надёжно. И не пиши в тексте фразы вроде «вот "
        "ссылка для добавления» или «ссылка ниже» — под сообщением появится "
        "именно КНОПКА, а не ссылка в тексте; обещание "
        "«ссылки» там, где будет кнопка, сбивает с толку. Просто подтверди "
        "коротко, что событие подготовлено, не упоминая механику."
    ),
    "create_maps_link": (
        "Если нужна ссылка-навигатор на место (чтобы пользователь мог "
        "проложить маршрут) — вызови create_maps_link с названием/адресом "
        "места, никогда не пиши такую ссылку сам. Кнопки для перехода в "
        "карты появятся снизу сами — не описывай их и не упоминай клик, но "
        "сам текст ответа всё равно должен быть полноценным: назови место и "
        "адрес словами, как в обычном ответе без ссылки, а не только "
        "«вот ссылка, переходи» — кнопка это ДОПОЛНЕНИЕ к ответу, а не "
        "замена его содержимого. Это текстовый поиск, не точная точка на "
        "карте — короткое общее название может совпасть с несколькими "
        "местами, и пользователь не поймёт, куда его привело. Если по "
        "названию похоже, что мест с таким именем может быть несколько "
        "(нет точного адреса/района/города из web_search или заметки) — "
        "либо уточни у пользователя, какое именно место он имеет в виду, "
        "либо клади в query максимум конкретики, которая реально есть."
    ),
    "create_reminder": (
        "Когда в разговоре всплывает что-то с конкретной датой/временем "
        "(пункт списка со сроком, событие, дедлайн) — можно предложить "
        "создать напоминание, но НЕ создавай его молча: спроси явно, нужно "
        "ли (как /remind в Slack — сначала спрашивает), и на какое время, "
        "если оно не названо. Создавай create_reminder только после "
        "согласия. trigger_at — только из того, что явно сказал "
        "пользователь, не угадывай. Если напоминание относится к "
        "конкретной заметке/списку — передай item_id (и entry_id, если это "
        "конкретный пункт списка, из get_list), чтобы клик по уведомлению "
        "вёл сразу туда, а не просто в общий список."
    ),
    "read_website": (
        "Если пользователь прислал ссылку на сайт и просит её прочитать, "
        "пересказать или спрашивает, что там написано — вызови read_website "
        "с этой ссылкой. Если сообщение пользователя — ГОЛАЯ ссылка БЕЗ "
        "вопроса (просто вставил URL и всё) — не читай молча сама: "
        "предложи через suggest_replies ('Прочитать эту страницу?') и "
        "прочитай только после согласия — это реальный сетевой запрос "
        "вовне, не мгновенный и не бесплатный по времени, чтобы делать "
        "его на каждую случайно присланную ссылку без спроса. Не путай с "
        "web_search — тот ищет ПО интернету, этот читает КОНКРЕТНУЮ уже "
        "известную ссылку. Если тул вернул error — так и скажи "
        "пользователю (сайт не открылся, или это не обычная HTML-страница, "
        "или контент грузится через JavaScript и не читается), не "
        "выдумывай содержимое."
    ),
}


def _build_system_prompt(
    memory_facts: list[str], custom_instructions: str, enabled_tools: set[str], disabled_tools: set[str]
) -> str:
    # ISO, не локализованное имя дня недели — strftime("%A") в контейнере
    # без ru_RU-локали всё равно выдал бы английское имя, а модели ISO-даты
    # достаточно, чтобы правильно резолвить "на этой неделе"/"вчера" и т.п.
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    prompt = f"Сегодняшняя дата: {today} (ISO, UTC).\n\n" + SYSTEM_PROMPT_BASE
    if SHOW_NOTE_IMAGES_SKILL not in disabled_tools:
        prompt += "\n\n" + SHOW_NOTE_IMAGES_PROMPT_FRAGMENT
    for tool_name, fragment in TOOL_PROMPT_FRAGMENTS.items():
        if tool_name in enabled_tools:
            prompt += "\n\n" + fragment
    if memory_facts:
        facts_block = "\n".join(f"- {f}" for f in memory_facts)
        prompt += f"\n\nЗапомненные факты об этом пользователе (используй их, не спрашивай заново):\n{facts_block}"
    if custom_instructions.strip():
        prompt += f"\n\nДополнительные инструкции от пользователя:\n{custom_instructions.strip()}"
    return prompt


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _default_space_id(db: AsyncSession, user_id: uuid.UUID) -> uuid.UUID:
    """"Домашний" спейс для новых диалогов ассистента, когда пользователь
    явно не выбирает спейс — самый старый спейс пользователя, детерминированно
    и стабильно между запросами (не "текущий активный спейс сайдбара", как
    было раньше: тогда новый диалог мог уйти в случайный спейс просто
    потому, что пользователь до этого листал заметки где-то ещё)."""
    space_id = (
        await db.execute(
            select(Space.id)
            .join(SpaceMember, SpaceMember.space_id == Space.id)
            .where(SpaceMember.user_id == user_id)
            .order_by(Space.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if space_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "У пользователя нет ни одного спейса")
    return space_id


async def _get_dialog(db: AsyncSession, user: User, dialog_id: uuid.UUID) -> Item:
    item = await db.get(Item, dialog_id)
    if item is None or item.material_type != "dialog" or item.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диалог не найден")
    await ensure_space_access(db, item.space_id, user.id)
    return item


def _serialize(item: Item) -> DialogOut:
    return DialogOut(
        id=item.id,
        space_id=item.space_id,
        title=item.title,
        created_at=item.created_at,
        updated_at=item.updated_at,
        messages=item.properties.get("messages", []),
    )


def _to_llm_messages(records: list[dict], system_prompt: str) -> list[Message]:
    messages = [Message(role="system", content=system_prompt)]
    for r in records:
        role = r["role"]
        if role == "assistant":
            tool_calls = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc in r.get("tool_calls", [])
            ]
            content = r.get("content", "")
            # Ход, где модель вызвала только suggest_replies (чипы UI, не
            # настоящий tool_call — см. комментарий в run_dialog_turn) без
            # сопроводительного текста, хранится с пустым content и без
            # tool_calls. При проигрывании истории обратно в LLM такое
            # assistant-сообщение (пусто и там, и там) Mistral отклоняет
            # 400-й — реальный баг, пойманный через Telegram-кнопки, но
            # актуальный и для веба. Такой ход не несёт информации для
            # модели, просто не включаем его в историю запроса.
            if not content.strip() and not tool_calls:
                continue
            messages.append(Message(role="assistant", content=content, tool_calls=tool_calls))
        elif role == "tool":
            messages.append(
                Message(role="tool", content=r.get("content", ""), tool_call_id=r.get("tool_call_id"), name=r.get("name"))
            )
        else:
            messages.append(Message(role=role, content=r.get("content", "")))
    return messages


# URL-часть допускает один уровень вложенных скобок (типичное для реальных
# ссылок вроде .../wiki/Something_(disambiguation)) — простой [^)]+ обрывает
# совпадение на первой же ")" внутри самого URL и оставляет хвост ссылки
# видимым мусорным текстом (поймали на реальном придуманном calendar.google.com
# URL с "(MTP)" в параметре location).
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://(?:[^\s()]|\([^\s()]*\))+)\)")


def _strip_unverified_links(text: str, allowed_urls: set[str]) -> str:
    """Промпт один не удерживает модель от выдумывания правдоподобных
    ссылок (особенно Google Maps с координатами) — проверено на практике,
    инструкция "не выдумывай ссылки" не сработала. Поэтому режем на уровне
    кода: ссылка остаётся кликабельной, только если её URL буквально
    встречался в результатах web_search этого хода; иначе остаётся просто
    текст без ссылки."""

    def replace(match: re.Match[str]) -> str:
        link_text, url = match.group(1), match.group(2)
        return match.group(0) if url in allowed_urls else link_text

    return _MARKDOWN_LINK_RE.sub(replace, text)


def _looks_like_leaked_tool_call(content: str, tool_names: set[str]) -> bool:
    """Модель иногда пишет вызов инструмента как текст ответа вместо
    настоящего tool_call — content начинается с имени реального тула и
    заканчивается JSON-объектом (между ними бывает мусор — наблюдали живьём
    случайное лишнее слово). Настоящий текстовый ответ так не выглядит,
    поэтому ложных срабатываний на обычных ответах практически не бывает."""
    stripped = content.strip()
    if not stripped.endswith("}"):
        return False
    return any(stripped.startswith(name) for name in tool_names)


def _flatten_transcript(records: list[dict]) -> str:
    # str(...) — подстраховка: если content когда-нибудь снова окажется не
    # строкой (см. MistralClient._from_wire), это не должно ронять весь
    # запрос ДО db.commit() и терять реплику пользователя целиком.
    parts = [str(r["content"]) for r in records if r["role"] in ("user", "assistant") and r.get("content")]
    return "\n\n".join(parts)


@router.get("", response_model=list[DialogSummaryOut])
async def list_dialogs(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> list[DialogSummaryOut]:
    """Диалоги сразу по всем спейсам пользователя — ассистент не привязан
    к одному спейсу с точки зрения пользователя (обсуждено явно: инструменты
    и так уже читают/меняют объекты в любом спейсе, а раньше список чатов
    был жёстко разделён по спейсам, как заметки — жалоба "не вижу чат с
    телефона на компе", потому что разговор через Telegram-бота лежит в
    своём отдельном спейсе "Telegram")."""
    query = (
        select(Item, Space.name)
        .join(Space, Space.id == Item.space_id)
        .join(SpaceMember, SpaceMember.space_id == Item.space_id)
        .where(SpaceMember.user_id == user.id, Item.material_type == "dialog", Item.deleted_at.is_(None))
        .order_by(Item.updated_at.desc())
    )
    rows = (await db.execute(query)).all()
    return [
        DialogSummaryOut(
            id=item.id, space_id=item.space_id, space_name=space_name, title=item.title,
            created_at=item.created_at, updated_at=item.updated_at,
        )
        for item, space_name in rows
    ]


@router.post("", response_model=DialogOut, status_code=status.HTTP_201_CREATED)
async def create_dialog(
    payload: DialogCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DialogOut:
    if payload.space_id is not None:
        await ensure_space_access(db, payload.space_id, user.id)
        space_id = payload.space_id
    else:
        space_id = await _default_space_id(db, user.id)
    item = await create_item_row(
        db,
        space_id=space_id,
        author_id=user.id,
        material_type="dialog",
        title=payload.title or "Новый диалог",
        properties={"messages": []},
    )
    return _serialize(item)


@router.get("/{dialog_id}", response_model=DialogOut)
async def get_dialog(
    dialog_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DialogOut:
    item = await _get_dialog(db, user, dialog_id)
    return _serialize(item)


@router.delete("/{dialog_id}/messages/{message_id}", response_model=DialogOut)
async def delete_message(
    dialog_id: uuid.UUID,
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DialogOut:
    item = await _get_dialog(db, user, dialog_id)
    records: list[dict] = list(item.properties.get("messages", []))

    index = next((i for i, r in enumerate(records) if r["id"] == message_id), None)
    if index is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сообщение не найдено")

    target = records[index]
    if target["role"] == "tool":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Нельзя удалить результат инструмента отдельно — удали связанную реплику"
        )

    # Реплика ассистента с tool_calls тянет за собой свои "tool"-записи —
    # иначе при следующей отправке история для LLM была бы битой (висящий
    # tool_call без результата).
    tool_call_ids = {tc["id"] for tc in target.get("tool_calls", [])}
    remaining = [
        r
        for i, r in enumerate(records)
        if i != index and not (r["role"] == "tool" and r.get("tool_call_id") in tool_call_ids)
    ]

    item.properties = {**item.properties, "messages": remaining}
    item.content = _flatten_transcript(remaining)
    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "dialogs")
    return _serialize(item)


async def run_dialog_turn(db: AsyncSession, user: User, item: Item, content: str) -> list[dict]:
    """Один ход агентного цикла над диалогом `item`: добавляет реплику
    пользователя, гоняет LLM+тулы до финального ответа или потолка
    итераций, коммитит и уведомляет по WS. Общее ядро для HTTP-эндпоинта
    ниже (send_message) и Telegram-моста (app/telegram_bot.py) — та же
    логика должна вести себя одинаково в обоих местах, а не дублироваться."""
    records: list[dict] = list(item.properties.get("messages", []))
    records.append({"id": str(uuid.uuid4()), "role": "user", "content": content, "created_at": _now_iso()})

    if item.title in ("", "Новый диалог"):
        item.title = content[:60]

    settings = get_settings()
    disabled_tool_names = set(user.disabled_tools)
    tool_definitions = get_tool_definitions(disabled=disabled_tool_names)
    ctx = ToolContext(db=db, user_id=user.id, space_id=item.space_id)
    web_search_calls = 0
    max_web_search_calls = settings.web_search_max_calls_per_turn
    verified_urls: set[str] = set()
    used_web_search = False
    used_advanced_web_search = False

    if not settings.llm_api_key:
        records.append(
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": "Ассистент ещё не настроен: не задан ключ LLM-провайдера (LLM_API_KEY).",
                "created_at": _now_iso(),
            }
        )
        item.properties = {**item.properties, "messages": records}
        item.content = _flatten_transcript(records)
        await db.commit()
        await db.refresh(item)
        return records

    llm_client = get_llm_client()

    memories_result = await db.execute(
        select(AssistantMemory.content).where(AssistantMemory.user_id == user.id).order_by(AssistantMemory.created_at)
    )
    memory_facts = [row[0] for row in memories_result.all()]
    enabled_tool_names = {d.name for d in tool_definitions}
    system_prompt = _build_system_prompt(memory_facts, user.custom_instructions, enabled_tool_names, disabled_tool_names)
    tool_call_leak_retried = False

    for _ in range(MAX_TOOL_ITERATIONS):
        try:
            response = await llm_client.chat(_to_llm_messages(records, system_prompt), tool_definitions)
        except httpx.HTTPError:
            logger.exception("Ошибка обращения к LLM-провайдеру")
            records.append(
                {
                    "id": str(uuid.uuid4()),
                    "role": "assistant",
                    "content": "Не получилось получить ответ от LLM-провайдера — попробуй ещё раз чуть позже.",
                    "created_at": _now_iso(),
                }
            )
            break
        assistant_msg = response.message

        # Изредка модель вместо настоящего tool_call пишет его как обычный
        # текст ("create_calendar_event {...}") — реального вызова не
        # происходит (событие не создаётся), а пользователь видит в чате
        # сырой JSON вместо результата. Поймано вживую на реальном разговоре
        # (репорт пользователя: "ссылка на календарь не создалась"). Раз —
        # молча повторяем тот же запрос без добавления в историю (обычно
        # помогает), не удалось второй раз — показываем честную ошибку
        # вместо мусора.
        if not assistant_msg.tool_calls and _looks_like_leaked_tool_call(assistant_msg.content, enabled_tool_names):
            logger.warning("Похоже на утёкший tool_call текстом вместо настоящего вызова: %r", assistant_msg.content[:200])
            if not tool_call_leak_retried:
                tool_call_leak_retried = True
                continue
            records.append(
                {
                    "id": str(uuid.uuid4()),
                    "role": "assistant",
                    "content": "Не получилось выполнить действие — попробуй переформулировать запрос.",
                    "created_at": _now_iso(),
                }
            )
            break

        # suggest_replies — не настоящий тул с побочным эффектом, а разметка
        # для UI (чипы вместо свободного текста). Не кладём его в tool_calls
        # (не показываем как техническую "🔧 вызвал тул" строку) и не зовём
        # dispatch — сразу после него всегда конец хода, ждём клика/ввода.
        real_tool_calls = [tc for tc in assistant_msg.tool_calls if tc.name != "suggest_replies"]
        suggest_calls = [tc for tc in assistant_msg.tool_calls if tc.name == "suggest_replies"]

        assistant_record: dict = {
            "id": str(uuid.uuid4()),
            "role": "assistant",
            "content": _strip_unverified_links(assistant_msg.content, verified_urls),
            "created_at": _now_iso(),
        }
        if real_tool_calls:
            assistant_record["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in real_tool_calls
            ]
        elif assistant_record["content"].strip():
            # Модель иногда отвечает по памяти о более раннем результате
            # search_base/get_note вместо повторного вызова в этом ходу —
            # даже после явной инструкции в промпте звать тул заново
            # (наблюдалось дважды подряд вживую на реальном диалоге, промпт
            # не гарантия поведения модели). Карточки на фронте
            # (TicketResultCards/NoteResultLinks/LinkPreviewResultCards)
            # читают tool_calls именно текущего сообщения — без этого ответ
            # выглядел бы без единой рабочей ссылки/кнопки, при том что
            # данные для карточки уже реально есть в истории диалога.
            #
            # display_tool_calls, НЕ tool_calls: реальная поломка, пойманная
            # вживую — _to_llm_messages читает именно "tool_calls" и
            # реконструирует по нему assistant-сообщение с tool_calls для
            # LLM API, а Mistral (как и весь OpenAI-совместимый протокол)
            # требует, чтобы такое сообщение было НЕМЕДЛЕННО продолжено
            # tool-сообщениями с результатами — которых тут нет (настоящего
            # вызова не было). Итог был 400 Bad Request на КАЖДЫЙ следующий
            # ход этого диалога, включая уже сохранённые в БД записи —
            # ломало реальный диалог пользователя намертво. display_tool_calls
            # — отдельное поле, которое _to_llm_messages не читает вовсе
            # (см. ниже), только фронт для отрисовки карточек.
            for prior in reversed(records):
                if prior.get("role") == "assistant" and prior.get("tool_calls"):
                    assistant_record["display_tool_calls"] = prior["tool_calls"]
                    break
        if suggest_calls:
            options: list[str] = []
            for tc in suggest_calls:
                options.extend(str(o).strip() for o in tc.arguments.get("options", []) if str(o).strip())
            assistant_record["suggested_replies"] = options
        records.append(assistant_record)

        if not assistant_msg.tool_calls:
            break

        for tc in real_tool_calls:
            if tc.name == "web_search":
                web_search_calls += 1
                if web_search_calls > max_web_search_calls:
                    result: dict = {"error": "Лимит веб-поиска на этот ход исчерпан"}
                else:
                    used_web_search = True
                    if str(tc.arguments.get("depth", "basic")).strip().lower() == "advanced":
                        used_advanced_web_search = True
                    result = await dispatch(tc.name, ctx, tc.arguments, disabled=disabled_tool_names)
                    for search_result in result.get("results", []) or []:
                        url = search_result.get("url")
                        if url:
                            verified_urls.add(url)
            else:
                result = await dispatch(tc.name, ctx, tc.arguments, disabled=disabled_tool_names)

            records.append(
                {
                    "id": str(uuid.uuid4()),
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": json.dumps(result, ensure_ascii=False),
                    "created_at": _now_iso(),
                }
            )

        if suggest_calls:
            break
    else:
        records.append(
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": "Не удалось завершить ответ за отведённое число шагов — попробуй переформулировать запрос.",
                "created_at": _now_iso(),
            }
        )

    # Модель не всегда помнит предложить более глубокий поиск сама (иногда
    # просто пишет вопрос текстом вместо вызова suggest_replies) — не
    # полагаемся только на промпт, гарантируем чип кодом, если в этом ходе
    # был хотя бы один web_search и ни один не был depth=advanced.
    if used_web_search and not used_advanced_web_search and records and records[-1]["role"] == "assistant":
        chip = "Поискать глубже"
        existing = records[-1].get("suggested_replies") or []
        if chip not in existing:
            records[-1]["suggested_replies"] = [*existing, chip]

    item.properties = {**item.properties, "messages": records}
    item.content = _flatten_transcript(records)
    await db.commit()
    await db.refresh(item)
    await realtime.notify_space(item.space_id, "dialogs")
    return records


@router.post("/{dialog_id}/messages", response_model=DialogOut)
async def send_message(
    dialog_id: uuid.UUID,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DialogOut:
    item = await _get_dialog(db, user, dialog_id)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустое сообщение")
    await run_dialog_turn(db, user, item, content)
    return _serialize(item)

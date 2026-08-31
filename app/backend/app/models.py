import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Добавляется к системному промпту ассистента, не заменяет его —
    # базовые правила (безопасность, инструменты) остаются фиксированными
    # в коде, пользователь настраивает поведение поверх них, а не вместо.
    custom_instructions: Mapped[str] = mapped_column(Text, default="", server_default="")
    # Имена тулов из app/tools/registry.py, которые пользователь выключил
    # в настройках («Умения ассистента») — пустой список значит всё включено.
    disabled_tools: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    # voice_id для Palabra TTS как есть — "default_low"/"default_high"
    # (built-in мужской/женский) или свой id голоса с Palabra Platform.
    tts_voice: Mapped[str] = mapped_column(String(128), default="default_low", server_default="default_low")
    # Гейтит авто-обработку загрузок (OCR картинок, расшифровка видео,
    # авто-OCR PDF-сканов) — по умолчанию включена, поведение для тех,
    # кто настройку не трогал, не меняется.
    auto_process_uploads: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Per-user переопределение LLM-провайдера ассистента ("" — глобальный
    # дефолт из LLM_PROVIDER). Живой переключатель в настройках для A/B
    # сравнения провайдеров без передеплоя — см. llm/factory.py.
    llm_provider: Mapped[str] = mapped_column(String(32), default="", server_default="")


class InviteCode(Base):
    """Инвайт-код регистрации — создаётся существующим пользователем в
    настройках (реальный запрос: "хочу сам выдавать код тому, кого
    добавляю", вместо единого секрета в vault, который надо было бы
    просить у меня каждый раз). Одноразовый: used_at проставляется в
    момент успешной регистрации, повторно использовать нельзя."""

    __tablename__ = "invite_codes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Ограниченный срок жизни — если код успели где-то засветить, не
    # остаётся годным навсегда (реальный найденный баг открытой
    # регистрации был именно про "то, что не ограничено по времени,
    # рано или поздно найдут").
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    used_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Space(Base):
    __tablename__ = "spaces"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Сейф (ТЗ §16.2, Фаза 4 раньше срока) — E2E-шифрование на клиенте,
    # бэкенд НИКОГДА не видит plaintext title/content этого спейса (только
    # непрозрачные blob'ы в properties.vault каждого item). Поэтому ИИ,
    # полнотекстовый поиск, OCR, авто-теги для него принципиально
    # невозможны — не ограничение, а прямое следствие того, что сервер не
    # может прочитать то, что не может расшифровать. vault_salt — не
    # секрет (нужна, чтобы на клиенте заново вывести тот же ключ из
    # пароля). vault_verifier — известная строка, зашифрованная ключом
    # сейфа при создании: клиент при разблокировке пробует её
    # расшифровать кандидатным ключом — AES-GCM сам обнаружит неверный
    # пароль по несовпадению тега аутентичности, без единого обращения к
    # серверу для проверки. Оба поля осмысленны только вместе с
    # is_vault=true и заполняются один раз при создании — эндпоинт не
    # даёт превратить обычный спейс в сейф и обратно (миграция
    # существующего plaintext-контента — отдельная, более рискованная
    # задача, сознательно не в этой версии).
    is_vault: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    vault_salt: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vault_verifier: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Публичные страницы — спейс-контейнер: заметку сначала кладут сюда,
    # только тогда для неё можно настроить публичную ссылку
    # (routers/items.py::share_item). Взаимоисключающе с is_vault
    # (проверка в routers/spaces.py::create_space) — сейф и публичный
    # доступ противоречат друг другу по смыслу.
    is_public_pages: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class SpaceMember(Base):
    __tablename__ = "space_members"

    space_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SpaceInvite(Base):
    """Ссылка-приглашение в шареный спейс — отдельно от InviteCode
    (та — про регистрацию нового пользователя вообще, эта — про то, чтобы
    ВСТУПИТЬ уже зарегистрированному в конкретный спейс). Добавление по
    нику происходит без этой таблицы, напрямую (см. routers/spaces.py) —
    ссылка нужна только когда заранее неизвестно, кто именно перейдёт."""

    __tablename__ = "space_invites"

    id: Mapped[uuid.UUID] = _uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[uuid.UUID] = _uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tags_user_name"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Item(Base):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = _uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    folder_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    material_type: Mapped[str] = mapped_column(String(50), default="note", index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Публичные страницы (routers/public.py) — is_public/share_token/
    # share_password_hash существуют с самой первой миграции, но были
    # мертвы (ничто их не читало/не писало) до этой фичи. share_revoked
    # сознательно НЕ используется — избыточен относительно is_public
    # (выключить публикацию = снять is_public, отдельного "отозвать" не
    # нужно, это то же самое действие).
    is_public: Mapped[bool] = mapped_column(Boolean, default=False)
    share_token: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    share_password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    share_revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    # null — «до отмены» (владелец сам выключает публикацию, см. выше).
    share_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    share_single_use: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Момент, когда одноразовую ссылку открыли — второй показ САМОГО
    # содержимого заметки после этого запрещён (routers/public.py); файлы,
    # вложенные в неё, эту проверку сознательно не повторяют (см. докстринг
    # routers/public.py).
    share_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Мягкое удаление: с появлением AI-ассистента с правом на delete_note
    # цена ошибки модели — безвозвратная потеря заметки. NULL = не удалена.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class ItemTag(Base):
    __tablename__ = "item_tags"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Авто-тег от LLM-классификатора (app/autotag.py), не от человека —
    # визуально помечается на фронте и легко удаляется (ТЗ §8.2).
    auto: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Upload(Base):
    """Файлы, вставленные в заметки (картинки редактора). Отдельная лёгкая
    таблица нужна только для проверки доступа при отдаче файла — сам файл
    лежит на диске в UPLOAD_DIR под именем upload.id."""

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = _uuid_pk()
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Фоновая расшифровка содержимого файла — речь из видео
    # (app/transcription.py) или описание/OCR картинки (app/vision.py).
    # Общие поля для обоих: по смыслу одно и то же ("вытащить текст из
    # файла в фоне"), отдельные таблицы ради этого не нужны. none — для
    # файлов, которые не обрабатываются (не видео и не изображение).
    transcription_status: Mapped[str] = mapped_column(String(20), default="none", server_default="none")
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)


class ItemVersion(Base):
    __tablename__ = "item_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Feedback(Base):
    """Отзывы из плавающей кнопки в UI. Не items: это не пользовательский
    контент базы, а данные о самом продукте — не привязано к спейсу."""

    __tablename__ = "feedback"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    page_url: Mapped[str] = mapped_column(String(500), default="")
    screenshot_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class DebugLog(Base):
    """Точечная клиентская диагностика для конкретного бага (белый экран
    в standalone PWA, не воспроизводится в песочнице) — не общий механизм
    логирования, временная таблица под одно расследование. Не items:
    не пользовательский контент, только техническое состояние интерфейса."""

    __tablename__ = "debug_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    event: Mapped[str] = mapped_column(String(100))
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Notification(Base):
    """Расширяемый центр уведомлений (ТЗ §13). Сейчас реальных источников
    ещё нет (приглашения в спейсы, изменения в списках — Фаза 1+ дальше),
    таблица заведена заранее под них. type — свободная строка-код события
    ("space_invite", "list_changed", ...), payload — JSONB под детали,
    специфичные для конкретного типа."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    # NULL — обычное немедленное уведомление. С датой в будущем — не
    # отдаётся списком, пока не наступит (напоминания ассистента).
    trigger_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # NULL — ещё не отправлено во внешние каналы (Telegram/Web Push);
    # диспетчер (app/notification_dispatch.py) проставляет после отправки,
    # чтобы не слать одно и то же уведомление повторно на каждом тике.
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # "Выполнено" — независимая ось от trigger_at/read_at (реальная жалоба:
    # напоминание с уже прошедшим trigger_at пользователь мысленно всё
    # равно считает активным, пока не отметил сделанным явно; путать
    # "время прошло" с "решено" — и есть баг). NULL — активное, вне
    # зависимости от того, наступило ли уже trigger_at.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushSubscription(Base):
    """Web Push подписка браузера (не Telegram) — endpoint/ключи, что
    возвращает PushManager.subscribe() на фронте. Один пользователь может
    иметь несколько (разные устройства/браузеры)."""

    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    p256dh: Mapped[str] = mapped_column(Text)
    auth: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TelegramLink(Base):
    """Привязка Telegram-аккаунта к notenotes-пользователю (простой Bot
    API, не MTProto — ТЗ, Фаза 2 «Каналы»). chat_id уникален: один
    Telegram-аккаунт не может быть привязан к двум пользователям сразу.
    Персональный спейс создаётся один раз при первой успешной привязке —
    у каждого пользователя свой, общего инбокса на всех нет намеренно."""

    __tablename__ = "telegram_links"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Текущий диалог с ассистентом для этого чата — NULL значит следующее
    # сообщение начнёт новый диалог лениво. /new сбрасывает обратно в NULL.
    active_dialog_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("items.id", ondelete="SET NULL"), nullable=True
    )


class TelegramLinkCode(Base):
    """Одноразовый код для /start в боте — генерируется из уже
    залогиненной веб-сессии (POST /api/telegram/link-code), живёт 10
    минут, удаляется сразу после использования."""

    __tablename__ = "telegram_link_codes"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmailInbox(Base):
    """Персональный адрес для приёма почты (см. routers/mail.py,
    routers/mail_webhook.py) — тот же принцип, что TelegramLink: постоянная
    1:1-привязка к пользователю, отдельный личный спейс создаётся один раз
    при первой генерации адреса. local_part — непубличный случайный токен
    (не сам email пользователя), спам-защита через неугадываемость, как и
    у Telegram-deep-link/SpaceInvite.token."""

    __tablename__ = "email_inboxes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    local_part: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Внешние адреса, которые пользователь считает СВОИМИ (личная почта,
    # рабочая и т.п.) — не путать с local_part выше (это приёмный
    # notenotes-адрес). Реальная жалоба: пересылаешь себе письмо — папка
    # называется по своему имени, потому что From: в пересланном письме —
    # это ты сам, а не оригинальный отправитель. Зная свои адреса,
    # mail_webhook.py может отличить "это я переслал/скопировал себе" от
    # "это письмо от постороннего" и искать реального собеседника
    # (mail_forward.py) вместо заголовка From:.
    own_addresses: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")


class LinkPreview(Base):
    """Кэш метаданных сайта для карточек ссылок в редакторе (Slack-style
    unfurl). Не items: это не пользовательский контент, а служебные данные
    о внешней странице — та же логика, что у Feedback/AssistantMemory.
    Кэш бессрочный: url уникален, повторная вставка ссылки на тот же сайт
    не должна снова дёргать его по сети."""

    __tablename__ = "link_previews"

    id: Mapped[uuid.UUID] = _uuid_pk()
    url: Mapped[str] = mapped_column(Text, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    favicon_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetch_failed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantMemory(Base):
    """Факты, которые AI-ассистент запомнил о пользователе между диалогами
    (ТЗ §10a, расширение). Не items: это не контент базы, а служебные
    данные о поведении ассистента — та же логика, что у Feedback/Notification.
    Управляется тулами remember_fact/list_memories/forget_fact и напрямую
    из настроек (см. routers/memories.py)."""

    __tablename__ = "assistant_memories"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class UrlCheckWidget(Base):
    """Состояние виджета «Проверить по ссылке» (tools/url_check.py) — url,
    поля, заголовки авторизации И результат последнего запроса. Раньше всё
    это (включая целиком тело последнего ответа, до 512 КБ) лежало прямо в
    content заметки — два реальных найденных следствия: 1) заголовки
    авторизации открытым текстом видны всем с доступом к спейсу и в
    бэкапах; 2) каждый клик «Обновить» гонял этот блоб через Yjs и
    создавал новый ItemVersion СО СТАРЫМ блобом внутри — чистое раздувание
    истории версий безо всякой пользы (обновление статуса заказа — не то,
    что нужно уметь откатывать). В заметке теперь только data-url-check-id
    (ссылка сюда) — и создание, и «Обновить» читают/пишут эту таблицу
    напрямую, не трогая content/Yjs/ItemVersion вообще. CASCADE на item —
    виджет умирает вместе с заметкой."""

    __tablename__ = "url_check_widgets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    fields: Mapped[list] = mapped_column(JSONB)
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryWidget(Base):
    """Состояние постоянного виджета отслеживания доставки (tools/
    track_delivery.py::insert_delivery_block). По образцу UrlCheckWidget: в
    content заметки лежит только data-delivery-id, а перевозчик/трек-номер и
    нормализованный результат последнего опроса — здесь. «Обновить»
    (routers/delivery_widgets.py) опрашивает API перевозчика через
    delivery.track и пишет только эту строку, не трогая content/Yjs/
    ItemVersion. last_result — JSON-строка нормализованного ответа, та же
    форма, что рисует карточка в чате. CASCADE на item."""

    __tablename__ = "delivery_widgets"

    id: Mapped[uuid.UUID] = _uuid_pk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    carrier: Mapped[str] = mapped_column(Text)
    tracking_number: Mapped[str] = mapped_column(Text)
    last_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

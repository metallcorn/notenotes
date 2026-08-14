from __future__ import annotations

import re

# Голая ссылка (или markdown-ссылка [текст](url)) на отдельной строке
# превращается в карточку сайта во фронтенде (LinkPreview.ts/
# NoteEditor.tsx: editorProps.handlePaste ловит вставку строки-URL целиком
# и создаёт узел linkPreview) — но это чисто клиентское поведение,
# срабатывающее только на paste, а не при обычном рендере markdown-
# контента. Заметки, созданные НЕ через paste в редакторе (Telegram-бот,
# ИИ-ассистент), никогда через этот путь не проходят — реальная жалоба:
# ассистент пишет опрятный markdown ("[readyfest.pl](url)" отдельной
# строкой), но карточка не появляется, ссылка остаётся голым текстом.
# Формат — тот же <a data-linkpreview>, что сериализует сам редактор
# (LinkPreview.ts), тогда его же parseHTML-правило (приоритет 100 над
# обычной ссылкой) подхватит узел при загрузке. Ссылки ВНУТРИ строки с
# другим текстом (не единственное содержимое строки) сюда не попадают —
# для них отдельный фронтенд-фикс (inline favicon-бейдж,
# InlineLinkFavicon.ts), сознательно другое поведение по прямому запросу
# пользователя (не путать эти два случая).
_SOLE_LINK_LINE_RE = re.compile(r"^\[[^\]]*\]\((https?://[^\s)]+)\)$|^(https?://\S+)$")

# Реальный запрос пользователя (после того, как увидел мини-бейдж на живой
# заметке): "хочу видеть везде красивые ссылки, а не просто мини-лого" —
# то есть строки вида "🔗 **Сайт фестиваля**: [readyfest.pl](url)" тоже
# должны получать полную карточку, не только инлайн-бейдж. Карточка —
# блочный узел (LinkPreview.ts, group: "block"), физически не может стоять
# ПОСЕРЕДИНЕ строки — поэтому подпись и ссылка разносятся на две строки:
# подпись остаётся текстом, ссылка сама по себе становится следующей
# строкой и подхватывается linkify_sole_link_lines. Короткий "лейбл до
# двоеточия, потом ссылка и БОЛЬШЕ НИЧЕГО" — узкий, безопасный паттерн:
# если после ссылки в строке есть ещё текст, или ссылок несколько, оно не
# совпадёт и останется как есть (инлайн-бейдж, InlineLinkFavicon.ts) — не
# пытаемся угадывать разбивку произвольной прозы.
_LABELED_LINK_LINE_RE = re.compile(
    r"^(?P<prefix>.{1,80}?[:：]\s*)(?P<link>\[[^\]]*\]\(https?://[^\s)]+\)|https?://\S+)\s*$"
)


def _split_labeled_link_lines(text: str) -> str:
    def _wrap(line: str) -> str:
        match = _LABELED_LINK_LINE_RE.match(line.strip())
        if not match:
            return line
        return f"{match.group('prefix').rstrip()}\n{match.group('link')}"

    return "\n".join(_wrap(line) for line in text.split("\n"))


def _esc_attr(s: str) -> str:
    # & — первым, иначе он же переэкранировал бы &quot;/&amp;, которые сам
    # только что вписал. Реальный найденный пробел security-ревью: раньше
    # экранировался только " — URL с "&" в query-строке (обычнейший
    # случай, ?a=1&b=2) уходил в HTML-атрибут как есть, не по спеке.
    return s.replace("&", "&amp;").replace('"', "&quot;")


def linkify_sole_link_lines(text: str) -> str:
    def _wrap(line: str) -> str:
        stripped = line.strip()
        match = _SOLE_LINK_LINE_RE.match(stripped)
        if not match:
            return line
        url = match.group(1) or match.group(2)
        return f'<a href="{_esc_attr(url)}" data-linkpreview></a>'

    return "\n".join(_wrap(line) for line in text.split("\n"))


def linkify_notes_content(text: str) -> str:
    """Полный проход: сначала разносим "лейбл: ссылка" на две строки, потом
    промоутим одиночные строки-ссылки в карточки. Порядок важен — вторая
    функция работает построчно и не увидит ссылку, если она ещё не
    отделена от лейбла."""
    return linkify_sole_link_lines(_split_labeled_link_lines(text))

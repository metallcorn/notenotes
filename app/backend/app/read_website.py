import re
from html.parser import HTMLParser

from app.link_preview import fetch_html

# Страница целиком, не только <head> (в отличие от link_preview.py) —
# лимит выше, но не безграничен, чтобы не тащить мегабайты разметки ради
# статьи на пару абзацев.
READ_MAX_BODY_BYTES = 5 * 1024 * 1024
MAX_TEXT_CHARS = 8000

_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "aside", "noscript"}
_BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr", "td", "th", "article", "section", "div"}


class _TextExtractor(HTMLParser):
    """Не полноценный Readability (оценка DOM-узлов по плотности текста) —
    простое исключение явно служебных тегов (навигация/скрипты/подвал).
    На статейных страницах этого обычно достаточно; на сложных SPA без
    серверного рендеринга может не вытащить почти ничего — это честная
    просадка качества, а не баг, см. README/план фичи."""

    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self._in_title = False
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            if self.title is None:
                self.title = data.strip()
            return
        if self._skip_depth > 0:
            return
        self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        # Схлопываем пробелы внутри строк, но сохраняем переносы,
        # расставленные на границах блочных тегов, — иначе весь текст
        # склеился бы в одну нечитаемую простыню.
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
        cleaned = "\n".join(line for line in lines if line)
        return re.sub(r"\n{3,}", "\n\n", cleaned)


async def fetch(url: str) -> dict:
    """Возвращает {"title", "url", "text", "truncated"} либо {"error": "..."} —
    никогда не бросает наружу, тул read_website сам решает, что сказать
    модели/пользователю при отказе."""
    fetched = await fetch_html(url, max_bytes=READ_MAX_BODY_BYTES)
    if fetched is None:
        return {"error": "Не удалось загрузить страницу (сайт не ответил, заблокирован или это не HTML)"}
    final_url, html = fetched

    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        return {"error": "Не удалось разобрать содержимое страницы"}

    text = parser.text()
    if not text:
        return {"error": "На странице не нашлось читаемого текста (возможно, контент грузится через JavaScript)"}

    truncated = len(text) > MAX_TEXT_CHARS
    return {
        "title": parser.title or "",
        "url": final_url,
        "text": text[:MAX_TEXT_CHARS],
        "truncated": truncated,
    }

"""Markdown ответа ассистента → HTML-разметка Telegram.

Ассистент пишет Markdown (так его показывает веб), а бот до 01.11 слал
текст как есть: «**«ушёл из дома»**» со звёздочками. Telegram понимает
ограниченный HTML (b, i, s, code, pre, a, blockquote) и ничего из
блочного Markdown, поэтому заголовки становятся жирными строками,
пункты списков — «•», остальное — тегами. Всё, что не разметка,
экранируется: иначе «<3» в тексте уронит отправку.

Чистые функции — проверяются тестом без Telegram.
"""

from __future__ import annotations

import html
import re

_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)")
_BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])|(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(?!\[)")
_TASK_RE = re.compile(r"^(\s*)[-*+]\s+\[([ xX])\]\s+")
_QUOTE_RE = re.compile(r"^\s{0,3}(?:&gt;|>)\s?")  # после html.escape «>» уже «&gt;»
_RULE_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_TAG_RE = re.compile(r"<[^>]+>")

_PLACEHOLDER = "\x00{}\x00"


def _inline(text: str) -> str:
    """Инлайновая разметка одной строки: вход уже экранирован, код вынесен."""
    text = _LINK_RE.sub(lambda m: f'<a href="{html.escape(html.unescape(m.group(2)), quote=True)}">{m.group(1)}</a>', text)
    text = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = _STRIKE_RE.sub(r"<s>\1</s>", text)
    text = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", text)
    return text


def markdown_to_telegram_html(markdown: str) -> str:
    stash: list[str] = []

    def keep(rendered: str) -> str:
        stash.append(rendered)
        return _PLACEHOLDER.format(len(stash) - 1)

    text = markdown.replace("\r\n", "\n")
    # Код — до экранирования и до всего остального: внутри него разметки нет.
    text = _FENCE_RE.sub(lambda m: keep(f"<pre>{html.escape(m.group(1).rstrip())}</pre>"), text)
    text = _CODE_RE.sub(lambda m: keep(f"<code>{html.escape(m.group(1))}</code>"), text)
    text = html.escape(text, quote=False)

    lines: list[str] = []
    for raw in text.split("\n"):
        if _RULE_RE.match(raw):
            continue
        line = raw
        heading = _HEADING_RE.match(line)
        if heading:
            lines.append(f"<b>{_inline(heading.group(1))}</b>")
            continue
        line = _QUOTE_RE.sub("", line)
        task = _TASK_RE.match(line)
        if task:
            mark = "☑" if task.group(2).strip() else "☐"
            line = f"{task.group(1)}{mark} {line[task.end():]}"
        else:
            line = _BULLET_RE.sub(r"\1• ", line)
        lines.append(_inline(line))
    text = "\n".join(lines)
    # Три и больше пустых строк подряд Telegram показывает как есть — глазу тяжело.
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    for index, rendered in enumerate(stash):
        text = text.replace(_PLACEHOLDER.format(index), rendered)
    return text


def markdown_to_plain(markdown: str) -> str:
    """Тот же разбор, но без тегов — запасной вариант, если Telegram не
    принял HTML: лучше текст без выделений, чем потерянный ответ."""
    rendered = markdown_to_telegram_html(markdown)
    return html.unescape(_TAG_RE.sub("", rendered))

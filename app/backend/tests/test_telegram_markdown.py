"""Markdown ответа ассистента → HTML Telegram (app/telegram_markdown.py).

Живой случай 01.11: «Готово! Анонс **«ушёл из дома»** отправлен…» пришёл
в бота со звёздочками — ответы слались простым текстом.
"""

from app.telegram_markdown import markdown_to_plain, markdown_to_telegram_html


def test_bold_italic_code_links():
    text = "Готово! Анонс **«ушёл из дома»** отправлен в *семейный* спейс, см. `announce` и [журнал](https://example.com/?item=1&x=2)."
    assert markdown_to_telegram_html(text) == (
        "Готово! Анонс <b>«ушёл из дома»</b> отправлен в <i>семейный</i> спейс, "
        'см. <code>announce</code> и <a href="https://example.com/?item=1&amp;x=2">журнал</a>.'
    )


def test_headings_lists_quotes_rules_and_escaping():
    text = "## Список\n\n- хлеб <3\n- молоко & сыр\n1. первое\n- [ ] купить\n- [x] сделано\n\n---\n> цитата\n\n__жирно__ и ~~зачёркнуто~~"
    assert markdown_to_telegram_html(text) == (
        "<b>Список</b>\n\n• хлеб &lt;3\n• молоко &amp; сыр\n1. первое\n☐ купить\n☑ сделано\n\n"
        "цитата\n\n<b>жирно</b> и <s>зачёркнуто</s>"
    )


def test_code_block_is_left_alone_and_underscores_in_words_survive():
    text = "Запусти:\n```bash\necho **not bold** <tag>\n```\nфайл my_file_name.py и snake_case не курсив, а _это_ да"
    assert markdown_to_telegram_html(text) == (
        "Запусти:\n<pre>echo **not bold** &lt;tag&gt;</pre>\nфайл my_file_name.py и snake_case не курсив, а <i>это</i> да"
    )


def test_plain_fallback_strips_tags_and_unescapes():
    assert markdown_to_plain("**a** < `b` и [c](https://x.y)") == "a < b и c"

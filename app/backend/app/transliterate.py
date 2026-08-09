"""Кириллица↔латиница для поиска (routers/search.py): полнотекстовый поиск
matches только буквально написанное — «Ульяна» никогда не найдёт заметку,
где то же имя лежит как «Ulyana» (папка Telegram по имени отправителя,
см. tickets_feature/sender-folders), и наоборот. Даёт лучший результат,
только когда пользователь пишет тем же алфавитом, что и в заметке — не
подменяет полноценный семантический/векторный поиск (обсуждается отдельно),
просто расширяет запрос вторым вариантом написания.

Практическая (не ГОСТ/ISO) транслитерация — так обычно и пишут имена
неформально: без апострофов на ъ/ь, х→kh, ц→ts, ч→ch, ш→sh, щ→shch."""

import re

_RU_TO_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh", "з": "z",
    "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

# Многобуквенные латинские сочетания — сначала длинные (жадно), иначе "yo"
# в "shchyo" никогда не соберётся, если сначала откусить одну "y".
_LAT_TO_RU_MULTI = (
    ("shch", "щ"), ("kh", "х"), ("ts", "ц"), ("ch", "ч"), ("sh", "ш"),
    ("yo", "ё"), ("yu", "ю"), ("ya", "я"), ("zh", "ж"),
)
_LAT_TO_RU_SINGLE = {
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е", "z": "з", "i": "и",
    "y": "й", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п", "r": "р",
    "s": "с", "t": "т", "u": "у", "f": "ф",
}

_CYRILLIC_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_LATIN_RE = re.compile(r"[a-z]", re.IGNORECASE)


def _ru_to_lat(word: str) -> str:
    return "".join(_RU_TO_LAT.get(ch, ch) for ch in word.lower())


def _lat_to_ru(word: str) -> str:
    word = word.lower()
    out: list[str] = []
    i = 0
    while i < len(word):
        for seq, ru in _LAT_TO_RU_MULTI:
            if word.startswith(seq, i):
                out.append(ru)
                i += len(seq)
                break
        else:
            out.append(_LAT_TO_RU_SINGLE.get(word[i], word[i]))
            i += 1
    return "".join(out)


def transliteration_variant(word: str) -> str | None:
    """Альтернативное написание того же слова другим алфавитом, или None,
    если слово не преимущественно кириллическое/латинское (числа, смешанный
    текст, уже нет смысла — вернуло бы то же самое или мусор) либо вариант
    совпал бы с оригиналом (например, слово без букв вовсе)."""
    if _CYRILLIC_RE.search(word):
        variant = _ru_to_lat(word)
    elif _LATIN_RE.search(word):
        variant = _lat_to_ru(word)
    else:
        return None
    return variant if variant and variant != word.lower() else None

#!/usr/bin/env python3
"""Сторож персональных данных: ничего живого из базы — ни в код, ни в историю.

ПОЧЕМУ. Репозиторий публичный. 18.10 перед первым пушем за два месяца
нашлось: PESEL владельца и жены с датами рождения, номера паспортов и
карты побыту, домашний адрес, почты и имена людей из писем, трек-номера,
рейс с датой. Всё — «живые примеры» в комментариях, тестах и сообщениях
коммитов. Пришлось переписывать 227 коммитов. Этот сторож — чтобы не
пришлось снова.

ДВА ИСТОЧНИКА.
  1. Общие шаблоны (PESEL, IBAN, телефон, паспорт, почта, «ul. … 12»).
     Работают где угодно, в том числе в CI, ничего о владельце не зная.
  2. Личный стоп-список — конкретные строки из базы (имена, номера,
     адреса). Лежит ВНЕ репозитория (~/.config/notenotes/pii-denylist*.txt):
     список в репозитории сам был бы утечкой. Собирается из боевой базы
     скриптом scripts/pii-denylist-refresh.sh, ручные дополнения —
     в pii-denylist.manual.txt рядом.

ЧТО ПРОВЕРЯЕТСЯ — только ДОБАВЛЕННЫЕ строки и сообщения коммитов:
  staged          индекс перед коммитом          (pre-commit)
  msg FILE        сообщение коммита              (commit-msg)
  push            всё, что уходит этим пушем     (pre-push, читает stdin)
  history [REV]   вся история до REV (по умолчанию все ветки) — аудит

Найденное печатается как «файл:строка: тип». Значение показывается только
с флагом --show: в CI лог публичный, и печатать в него найденный PESEL
значило бы самому же его опубликовать.

ЛОЖНОЕ СРАБАТЫВАНИЕ. Выдуманные тестовые значения — в
scripts/pii-allowlist.txt (по одному на строку). Либо пометка «pii-ok»
в той же строке. Обойти хук можно и `--no-verify`, но это должно быть
осознанным решением, а не привычкой.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ALLOWLIST = REPO / "scripts" / "pii-allowlist.txt"
DENY_DIR = Path(os.environ.get("NOTENOTES_PII_DIR", Path.home() / ".config" / "notenotes"))

# Файлы, где длинные цифры и «почты» — это хэши и метаданные пакетов.
SKIP_PATHS = re.compile(r"(^|/)(package-lock\.json|.*\.lock|.*\.svg|.*\.png|.*\.jpe?g|.*\.pdf|.*\.ico|.*\.woff2?)$")

# Почтовые домены, которые не принадлежат людям.
SAFE_EMAIL_DOMAINS = re.compile(
    r"@(?:[\w.-]+\.)?(?:example\.(?:com|org|net|pl)|example|notenotes\.example|anthropic\.com|"
    r"openssh\.com|libssh\.org|users\.noreply\.github\.com|localhost)$",
    re.I,
)

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # PESEL: 11 цифр (бывает и по одной в клетке — «9 2 1 2 …»).
    ("PESEL/11 цифр", re.compile(r"(?<![\d.\-/])(?:\d[ \t]?){10}\d(?![\d.\-/])")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?\d{4}){4,7}\b")),
    ("телефон", re.compile(r"\+\d{1,3}[ \-]?\(?\d{2,3}\)?(?:[ \-]?\d{2,4}){2,4}\b")),
    # Паспорт/карта побыту: две буквы + 7 цифр, или «75 1234567».
    ("номер документа", re.compile(r"\b[A-Z]{2}[ ]?\d{7}\b|\b\d{2} \d{7}\b")),
    ("почта", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")),
    ("адрес", re.compile(r"\bul\.\s*[A-ZŁŚŻŹĆŃÓ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ.\- ]{2,40}\s\d+[A-Za-z]?\b")),
]


def _load_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


ALLOWED = set(_load_lines(ALLOWLIST))


def _denylist() -> list[str]:
    items: list[str] = []
    for path in sorted(DENY_DIR.glob("pii-denylist*.txt")):
        items.extend(_load_lines(path))
    # Короткое совпадёт с чем попало — от 4 символов.
    return sorted({i for i in items if len(i) >= 4}, key=len, reverse=True)


# Разрешённое снимает и записи стоп-списка: логин владельца совпадает с
# публичным доменом сайта, и «metallcorn» в конфиге — не утечка.
DENY = [d for d in _denylist() if d not in ALLOWED]
DENY_LOWER = [d.lower() for d in DENY]
_DIGITS_ONLY = re.compile(r"\D")


def _digits(s: str) -> str:
    return _DIGITS_ONLY.sub("", s)


DENY_DIGITS = {_digits(d) for d in DENY if len(_digits(d)) >= 7 and len(_digits(d)) >= len(d) * 0.6}


def scan_line(line: str) -> list[tuple[str, str]]:
    """Список (тип, значение) в одной строке."""
    if "pii-ok" in line:
        return []
    found: list[tuple[str, str]] = []
    for kind, rx in PATTERNS:
        for m in rx.finditer(line):
            value = m.group(0).strip()
            if value in ALLOWED or any(a in value for a in ALLOWED if len(a) >= 6):
                continue
            if kind == "почта" and SAFE_EMAIL_DOMAINS.search(value):
                continue
            found.append((kind, value))
    low = line.lower()
    for d, dl in zip(DENY, DENY_LOWER):
        if dl in low:
            found.append(("стоп-список", d))
    line_digits = _digits(line)
    if DENY_DIGITS and len(line_digits) >= 7:
        for d in DENY_DIGITS:
            if d in line_digits and not any(d == _digits(v) for _, v in found):
                found.append(("стоп-список (цифры)", d))
    return found


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout


def scan_diff(diff: str, where: str) -> list[str]:
    """Добавленные строки патча: «+...» под заголовками «+++ b/путь»."""
    problems = []
    path, lineno, skip = "?", 0, False
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else raw[4:]
            skip = bool(SKIP_PATHS.search(path))
            continue
        if raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) - 1 if m else 0
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            lineno += 1
            if skip:
                continue
            for kind, value in scan_line(raw[1:]):
                problems.append((f"{where}{path}:{lineno}", kind, value))
        elif not raw.startswith("-"):
            lineno += 1
    return problems


def scan_text(text: str, where: str) -> list[tuple[str, str, str]]:
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        for kind, value in scan_line(line):
            problems.append((f"{where}:{n}", kind, value))
    return problems


def scan_commits(revs: list[str]) -> list[tuple[str, str, str]]:
    problems = []
    for rev in revs:
        short = rev[:8]
        msg = _git("log", "-1", "--format=%B", rev)
        problems += scan_text(msg, f"{short} сообщение")
        diff = _git("show", "--format=", "--no-color", "--unified=0", "--no-ext-diff", rev)
        problems += scan_diff(diff, f"{short} ")
    return problems


def report(problems, show: bool) -> int:
    if not problems:
        return 0
    seen = set()
    print("\n⛔ pii_guard: похоже на персональные данные — в публичный репозиторий это не должно попасть.\n", file=sys.stderr)
    for where, kind, value in problems:
        key = (where, kind, value)
        if key in seen:
            continue
        seen.add(key)
        tail = f"  «{value}»" if show else ""
        print(f"  {where}: {kind}{tail}", file=sys.stderr)
    print(
        "\nЗамени на выдуманное (Jan Kowalski, ul. Przykładowa 1, 90010112345, …).\n"
        "Выдуманное значение, которое всё равно ловится, — в scripts/pii-allowlist.txt\n"
        "или пометкой pii-ok в строке. Значения: запусти с --show.\n",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str]) -> int:
    show = "--show" in argv
    args = [a for a in argv if a != "--show"]
    mode = args[0] if args else "staged"

    if mode == "staged":
        diff = _git("diff", "--cached", "--no-color", "--unified=0", "--no-ext-diff")
        return report(scan_diff(diff, ""), show)

    if mode == "msg":
        text = Path(args[1]).read_text(encoding="utf-8")
        # Комментарии git (#) в сообщение не попадут.
        text = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
        return report(scan_text(text, "сообщение коммита"), show)

    if mode == "push":
        revs: list[str] = []
        for line in sys.stdin.read().splitlines():
            parts = line.split()
            if len(parts) != 4:
                continue
            local_sha = parts[1]
            if set(local_sha) == {"0"}:
                continue  # удаление ветки
            # Всё, чего ещё нет ни в одной удалённой ветке.
            revs += _git("rev-list", local_sha, "--not", "--remotes").split()
        return report(scan_commits(list(dict.fromkeys(revs))), show)

    if mode == "history":
        rev_args = args[1:] or ["--all"]
        revs = _git("rev-list", *rev_args).split()
        return report(scan_commits(revs), show)

    if mode == "tree":
        files = _git("ls-files").splitlines()
        problems = []
        for f in files:
            if SKIP_PATHS.search(f):
                continue
            try:
                text = (REPO / f).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            problems += scan_text(text, f)
        return report(problems, show)

    print(f"неизвестный режим: {mode}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

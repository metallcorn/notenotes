#!/usr/bin/env bash
# Собирает личный стоп-список для scripts/pii_guard.py из боевой базы.
#
# Список лежит ВНЕ репозитория (~/.config/notenotes/pii-denylist.db.txt,
# права 600): в репозитории он сам был бы утечкой. Ручные дополнения —
# в pii-denylist.manual.txt рядом, этот скрипт его не трогает.
#
# Что берётся (только то, что указывает на человека, а не обычные слова —
# стоп-список ищет подстроку без учёта регистра, и «Авто» поймало бы
# «Автосохранение»):
#   * имена и логины пользователей;
#   * папки отправителей в спейсах Telegram и «Почта» — это имена людей
#     и компаний;
#   * почты, телефоны, длинные номера (от 9 цифр), номера документов
#     (две буквы + 7 цифр) и адреса «ul. … N» из заметок и распознанного
#     текста файлов.
# Сейф не читается: там шифротекст.
#
# Запуск: scripts/pii-denylist-refresh.sh   (раз в неделю-две хватает)
set -euo pipefail
DIR="${NOTENOTES_PII_DIR:-$HOME/.config/notenotes}"
mkdir -p "$DIR" && chmod 700 "$DIR"
OUT="$DIR/pii-denylist.db.txt"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

sudo docker exec -i notenotes-postgres-1 psql -U notenotes notenotes -At > "$TMP" <<'SQL'
select json_build_object(
  'users', (select json_agg(json_build_array(username, name)) from users),
  'sender_folders', (
    select json_agg(distinct f.name) from folders f join spaces s on s.id = f.space_id
    where s.is_vault = false and (s.name ilike '%telegram%' or s.name ilike '%почт%' or s.name ilike '%mail%')
  ),
  'texts', (
    select json_agg(t) from (
      select i.content as t from items i join spaces s on s.id = i.space_id
        where s.is_vault = false and i.deleted_at is null
      union all
      select u.transcript from uploads u join spaces s on s.id = u.space_id
        where s.is_vault = false and u.transcript is not null
    ) x
  )
);
SQL

python3 -I - "$TMP" "$OUT" <<'PY'
import json, re, sys
raw = json.load(open(sys.argv[1]))
items = set()
for username, name in raw["users"] or []:
    for v in (username, name):
        if v and len(v) >= 4:
            items.add(v.strip())
for f in raw["sender_folders"] or []:
    # Одно короткое слово — скорее название канала («Geeks», «Лепра»),
    # чем человек, и как подстрока ловило бы обычный текст.
    if f and f not in ("Без отправителя",) and (" " in f.strip() or len(f) >= 6):
        items.add(f.strip())
blob = "\n".join(t for t in (raw["texts"] or []) if t)
safe = re.compile(r"@(?:[\w.-]+\.)?(?:example\.\w+|notenotes\.example|anthropic\.com)$", re.I)
for e in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", blob):
    if not safe.search(e):
        items.add(e.lower())
for p in re.findall(r"\+\d{1,3}[ \-]?\(?\d{2,3}\)?(?:[ \-]?\d{2,4}){2,4}", blob):
    items.add(p.strip())
for d in re.findall(r"(?<!\d)\d{9,}(?!\d)", blob):
    if not re.fullmatch(r"20\d{6}|(\d)\1+", d):
        items.add(d)
for d in re.findall(r"\b[A-Z]{2} ?\d{7}\b", blob):
    items.add(d)
for a in re.findall(r"\bul\.\s*[A-ZŁŚŻŹĆŃÓ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ.\- ]{2,40}\s\d+[A-Za-z]?\b", blob):
    items.add(a.strip())
with open(sys.argv[2], "w", encoding="utf-8") as out:
    out.write("# сгенерировано scripts/pii-denylist-refresh.sh — не править руками\n")
    for i in sorted(items):
        out.write(i + "\n")
print(f"{len(items)} строк -> {sys.argv[2]}")
PY
chmod 600 "$OUT"
MANUAL="$DIR/pii-denylist.manual.txt"
if [ ! -f "$MANUAL" ]; then
  printf '# Ручные дополнения стоп-списка: фамилии, адреса, места, то, чего нет в базе.\n' > "$MANUAL"
  chmod 600 "$MANUAL"
fi

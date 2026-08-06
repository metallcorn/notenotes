#!/bin/bash
# Создаёт inventory/group_vars/all/vault.yml за один запуск.
#
# Пароли Postgres/Redis/restic генерируются случайно, ключи MEGA S4 читаются
# из credentials-notenotes, парольная фраза LUKS собирается из слов.
# Ничего вводить не нужно, кроме пароля самого хранилища.
#
# Запускать в своём терминале: bash scripts/make-vault.sh

set -euo pipefail
cd "$(dirname "$0")/.."

VAULT=inventory/group_vars/all/vault.yml
CREDS=credentials-notenotes

if [[ -f $VAULT ]]; then
    echo "ОШИБКА: $VAULT уже существует." >&2
    echo "Править: ansible-vault edit $VAULT" >&2
    exit 1
fi

if [[ ! -f $CREDS ]]; then
    echo "ОШИБКА: нет файла $CREDS с ключами MEGA S4." >&2
    exit 1
fi

ACCESS_KEY=$(grep -oP '(?<=^aws_access_key_id=).*' "$CREDS" | tr -d "\"' \r")
SECRET_KEY=$(grep -oP '(?<=^aws_secret_access_key=).*' "$CREDS" | tr -d "\"' \r")

if [[ -z $ACCESS_KEY || -z $SECRET_KEY ]]; then
    echo "ОШИБКА: не удалось прочитать ключи из $CREDS." >&2
    exit 1
fi

# Фраза LUKS из слов, а не base64: её придётся вводить руками, возможно
# в VNC-консоли Netcup с несовпадающей раскладкой.
LUKS_PHRASE=$(grep -E '^[a-z]{4,8}$' /usr/share/dict/words \
    | shuf -n 5 --random-source=/dev/urandom \
    | paste -sd- -)

TMP=$(mktemp)
chmod 600 "$TMP"
trap 'shred -u "$TMP" 2>/dev/null || rm -f "$TMP"' EXIT

cat > "$TMP" <<EOF
---
vault_postgres_password: "$(openssl rand -base64 32)"
vault_redis_password: "$(openssl rand -base64 32)"
vault_luks_passphrase: "$LUKS_PHRASE"
vault_restic_password: "$(openssl rand -base64 32)"
vault_restic_s4_access_key: "$ACCESS_KEY"
vault_restic_s4_secret_key: "$SECRET_KEY"
EOF

echo
echo "Придумай пароль для ansible-vault — им шифруется весь файл секретов."
echo "Он будет спрашиваться при каждом прогоне Ansible."
echo
ansible-vault encrypt "$TMP" --output "$VAULT"
chmod 600 "$VAULT"

cat <<EOF

Готово: $VAULT

СОХРАНИ В МЕНЕДЖЕР ПАРОЛЕЙ ПРЯМО СЕЙЧАС:

  1) пароль ansible-vault — тот, что ты только что ввёл
  2) парольная фраза LUKS — $LUKS_PHRASE

Вторую вводишь на сервере после каждой перезагрузки.
Потеряешь любую — данные не восстановить.

Потом удали открытые копии ключей:
  shred -u credentials-notenotes
  rm -f ~/MEGA/Projects/notenotes/credentials-notenotes
EOF

SHELL := /bin/bash
ANSIBLE_PLAYBOOK := ansible-playbook --ask-vault-pass
INV := inventory/hosts.ini

.PHONY: help deps bootstrap harden platform stack backup site check lint unlock ping

help:
	@echo "Порядок первого запуска:"
	@echo "  make deps        — коллекции Ansible"
	@echo "  make bootstrap   — юзер metallcorn + ключ + sudo (под root)"
	@echo "  make harden      — sshd, ufw, fail2ban, обновления безопасности"
	@echo "  make platform    — docker + шифрованный том + edge-прокси"
	@echo "  make stack       — приложение notenotes: postgres+pgvector, redis"
	@echo "  make backup      — restic в MEGA S4 + таймеры"
	@echo ""
	@echo "Прочее:"
	@echo "  make site        — harden + platform + stack + backup одним прогоном"
	@echo "  make check       — прогон site в --check --diff, без изменений"
	@echo "  make lint        — ansible-lint"
	@echo "  make ping        — проверка связи"
	@echo "  make unlock      — открыть LUKS-том и поднять стек (после ребута)"

# Путь указан явно: pipx-пакет ansible несёт коллекции внутри своего venv,
# и ansible-lint из отдельного venv их не видит — make lint падал бы с
# unknown-module на вполне рабочих ролях.
deps:
	ansible-galaxy collection install -r requirements.yml -p ~/.ansible/collections

# Без --user root: пользователь для подключения задан внутри playbook'а.
# Пароль vault нужен и здесь, хотя сам playbook секретов не использует:
# Ansible читает все group_vars на старте play, включая зашифрованный vault.yml.
bootstrap:
	$(ANSIBLE_PLAYBOOK) -i $(INV) playbooks/00-bootstrap.yml

harden:
	$(ANSIBLE_PLAYBOOK) -i $(INV) playbooks/10-harden.yml

platform:
	$(ANSIBLE_PLAYBOOK) -i $(INV) playbooks/20-platform.yml

stack:
	$(ANSIBLE_PLAYBOOK) -i $(INV) playbooks/30-stack.yml

backup:
	$(ANSIBLE_PLAYBOOK) -i $(INV) playbooks/40-backup.yml

site:
	$(ANSIBLE_PLAYBOOK) -i $(INV) playbooks/site.yml

check:
	$(ANSIBLE_PLAYBOOK) -i $(INV) playbooks/site.yml --check --diff

lint:
	ansible-lint

ping:
	ansible -i $(INV) vps -m ping

# Интерактивный ввод парольной фразы LUKS происходит на сервере.
unlock:
	ssh -t notenotes 'sudo /usr/local/sbin/encrypted-unlock'

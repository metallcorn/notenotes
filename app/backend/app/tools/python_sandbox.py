from __future__ import annotations

import asyncio
import os
import pwd
import resource
import subprocess
import tempfile
from typing import Any

from app.llm.base import ToolDefinition
from app.tools.registry import ToolContext, ToolError

# Изоляция уровня subprocess, не отдельный контейнер (осознанный выбор —
# см. обсуждение с пользователем): непривилегированный линукс-юзер
# "sandbox" (заведён в Dockerfile), rlimit на CPU/память/процессы/файлы,
# пустое окружение (без секретов БД и API-ключей — они у backend-процесса
# в env, ребёнок его не наследует), таймаут по wall-clock поверх RLIMIT_CPU
# (тот считает только CPU-время, не сон/ожидание I/O). Сеть НЕ отрезана на
# уровне ОС — для этого нужны network namespaces, которых у контейнера без
# дополнительных привилегий нет; это принятый компромисс ради простоты.

_TIMEOUT_SECONDS = 5
_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
_OUTPUT_LIMIT = 4000
_SANDBOX_USERNAME = "sandbox"

RUN_PYTHON = ToolDefinition(
    name="run_python",
    description=(
        "Выполнить Python-код в изолированной песочнице — для точных вычислений: "
        "чисел, дат, агрегации данных из заметки/списка (сумма, среднее, сортировка "
        "и т.п.), а не для реальных действий с базой (для этого — свои тулы). Нет "
        "доступа к сети, файлам пользователя и переменным окружения — только чистые "
        "вычисления с тем, что явно передашь в коде. Доступны только стандартные "
        "модули Python (math, datetime, statistics, json, re, itertools, collections "
        "и т.п.) — сторонних библиотек (pandas, numpy, requests) НЕТ. Лимит времени "
        "5 секунд. Результат — то, что код вывел через print()."
    ),
    parameters={
        "type": "object",
        "properties": {"code": {"type": "string", "description": "Python-код; вывод результата — через print()"}},
        "required": ["code"],
    },
)


def _sandbox_user() -> pwd.struct_passwd | None:
    try:
        return pwd.getpwnam(_SANDBOX_USERNAME)
    except KeyError:
        return None


def _drop_privileges(uid: int, gid: int) -> None:
    os.setgroups([])
    os.setgid(gid)
    os.setuid(uid)
    resource.setrlimit(resource.RLIMIT_CPU, (_TIMEOUT_SECONDS, _TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (_MEMORY_LIMIT_BYTES, _MEMORY_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))


async def run_python(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    code = str(args.get("code", ""))
    if not code.strip():
        raise ToolError("Пустой код")

    user = _sandbox_user()
    if user is None:
        return {"error": "Песочница не настроена на сервере"}

    with tempfile.TemporaryDirectory(prefix="sandbox-") as tmpdir:
        os.chown(tmpdir, user.pw_uid, user.pw_gid)
        os.chmod(tmpdir, 0o700)

        try:
            proc = await asyncio.create_subprocess_exec(
                "python3",
                "-I",  # изолированный режим: игнорирует PYTHONPATH и user site-packages
                "-c",
                code,
                cwd=tmpdir,
                env={"PATH": "/usr/local/bin:/usr/bin", "HOME": tmpdir},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=lambda: _drop_privileges(user.pw_uid, user.pw_gid),
            )
        except OSError as e:
            return {"error": f"Не удалось запустить код: {e}"}

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT_SECONDS + 2)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {"error": f"Превышен лимит времени ({_TIMEOUT_SECONDS} сек) — упрости вычисление"}

    return {
        "stdout": stdout.decode("utf-8", errors="replace")[:_OUTPUT_LIMIT],
        "stderr": stderr.decode("utf-8", errors="replace")[:_OUTPUT_LIMIT],
        "exit_code": proc.returncode,
    }

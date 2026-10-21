import { useState } from "react";
import { Check, Copy, Plus, Trash2 } from "lucide-react";
import {
  useCreateMcpToken,
  useMcpAudit,
  useMcpTokens,
  useOAuthConnections,
  useRevokeMcpToken,
  useRevokeOAuthConnection,
} from "../api/hooks";
import Spinner from "./Spinner";

/** Машинные имена событий — человеческими словами (см. app/audit.py). */
const AUDIT_LABELS: Record<string, string> = {
  "mcp.tool": "Вызов инструмента",
  "mcp.token.created": "Создан токен",
  "mcp.token.revoked": "Отозван токен",
  "oauth.granted": "Разрешён доступ",
  "oauth.denied": "Отказано в доступе",
  "oauth.connection.revoked": "Отключено",
  "oauth.client.registered": "Клиент зарегистрирован",
  "oauth.code.replay": "Повторное использование кода",
  "oauth.refresh.replay": "Повторное использование токена",
};

/**
 * Подключение базы к внешнему ассистенту по MCP.
 *
 * Отдельным файлом, а не ещё одной секцией внутри SettingsModal: тот уже
 * 650 строк, и здесь своё состояние (показанный один раз токен), которое
 * не должно мешаться с остальными настройками.
 *
 * Токен показывается ЕДИНОЖДЫ — на сервере лежит только хэш, восстановить
 * нечего. Поэтому блок с ним намеренно заметный и не исчезает сам: закрыть
 * его должен человек, скопировав.
 */
export default function McpSettings() {
  const { data: tokens, isLoading } = useMcpTokens();
  const createToken = useCreateMcpToken();
  const revokeToken = useRevokeMcpToken();
  const { data: connections } = useOAuthConnections();
  const revokeConnection = useRevokeOAuthConnection();

  const [name, setName] = useState("");
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [copied, setCopied] = useState<"token" | "command" | null>(null);
  const [auditOpen, setAuditOpen] = useState(false);
  const { data: auditEntries } = useMcpAudit(auditOpen);

  const mcpUrl = `${window.location.origin}/api/mcp`;
  const command =
    `claude mcp add -t http notenotes ${mcpUrl} \\\n` +
    `  -H "Authorization: Bearer ${freshToken ?? "nn_..."}"`;

  async function handleCreate() {
    const created = await createToken.mutateAsync(name.trim());
    setFreshToken(created.token);
    setName("");
  }

  async function copy(text: string, what: "token" | "command") {
    await navigator.clipboard.writeText(text);
    setCopied(what);
    setTimeout(() => setCopied(null), 1500);
  }

  return (
    <div className="mb-6">
      <div className="mb-1 text-sm font-medium text-primary">Подключение по MCP</div>
      <div className="mb-2 text-xs text-subtle">
        Даёт внешнему ассистенту (Claude Code и подобным) доступ к заметкам, спискам и напоминаниям —
        искать, читать и создавать. Зашифрованный сейф недоступен всегда. Веб-поиск наружу не отдаётся:
        внешний ассистент ищет своим и наши лимиты не тратит.
      </div>
      <div className="mb-2 rounded border border-warning/40 bg-warning/10 px-2 py-1.5 text-xs text-warning">
        Содержимое заметок будет уходить тому сервису, которому вы дадите токен. Не выдавайте его тому,
        кому не готовы показать базу целиком.
      </div>

      {freshToken && (
        <div className="mb-3 rounded border border-strong bg-muted-hover p-2">
          <div className="mb-1 text-xs font-medium text-primary">
            Токен показан один раз — скопируйте сейчас
          </div>
          <div className="mb-2 flex items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded bg-surface px-2 py-1 text-xs">{freshToken}</code>
            <button
              onClick={() => copy(freshToken, "token")}
              title="Скопировать токен"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded border text-subtle hover:bg-surface"
            >
              {copied === "token" ? <Check size={13} /> : <Copy size={13} />}
            </button>
          </div>
          <div className="mb-1 text-xs text-subtle">Команда для Claude Code:</div>
          <div className="flex items-start gap-2">
            <pre className="min-w-0 flex-1 overflow-x-auto rounded bg-surface px-2 py-1 text-xs">{command}</pre>
            <button
              onClick={() => copy(command.replace(/\\\n\s*/g, " "), "command")}
              title="Скопировать команду"
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded border text-subtle hover:bg-surface"
            >
              {copied === "command" ? <Check size={13} /> : <Copy size={13} />}
            </button>
          </div>
          <button
            onClick={() => setFreshToken(null)}
            className="mt-2 text-xs text-subtle underline hover:text-primary"
          >
            Скопировал, скрыть
          </button>
        </div>
      )}

      {isLoading && <div className="text-sm text-subtle">Загрузка…</div>}
      {!isLoading && (tokens ?? []).length === 0 && !freshToken && (
        <div className="mb-2 text-sm text-subtle">Пока не подключено ни одного клиента</div>
      )}

      <ul className="space-y-1">
        {(tokens ?? []).map((t) => (
          <li key={t.id} className="flex items-center justify-between gap-2 rounded border px-2 py-1.5">
            <div className="min-w-0">
              <div className="truncate text-sm text-primary">{t.name || "Без названия"}</div>
              <div className="text-xs text-subtle">
                {/* Когда пользовались в последний раз — единственный способ
                    заметить забытый токен и отозвать его. */}
                {t.last_used_at
                  ? `Последний раз: ${new Date(t.last_used_at).toLocaleString()}`
                  : "Ещё не использовался"}
              </div>
            </div>
            <button
              onClick={() => revokeToken.mutate(t.id)}
              disabled={revokeToken.isPending}
              title="Отозвать"
              className="flex h-6 w-6 shrink-0 items-center justify-center text-subtle hover:text-danger disabled:opacity-50"
            >
              <Trash2 size={13} />
            </button>
          </li>
        ))}
      </ul>

      <div className="mt-2 flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !createToken.isPending) handleCreate();
          }}
          placeholder="Название, например «ноутбук»"
          className="min-w-0 flex-1 rounded border px-3 py-1.5 text-sm"
        />
        <button
          onClick={handleCreate}
          disabled={createToken.isPending}
          className="flex shrink-0 items-center justify-center rounded bg-accent px-3 py-1.5 text-sm text-on-accent disabled:opacity-50"
        >
          {createToken.isPending ? <Spinner size={14} className="text-white" /> : <Plus size={14} />}
        </button>
      </div>

      {connections !== undefined && connections.length > 0 && (
        <div className="mt-5">
          <div className="mb-1 text-sm font-medium text-primary">Подключено через Claude</div>
          <div className="mb-2 text-xs text-subtle">
            Подключения с claude.ai — они не используют токен выше. Отключение действует сразу.
          </div>
          <ul className="space-y-1">
            {connections.map((c) => (
              <li key={c.client_id} className="flex items-center justify-between gap-2 rounded border px-2 py-1.5">
                <div className="min-w-0">
                  <div className="truncate text-sm text-primary">{c.client_name}</div>
                  <div className="text-xs text-subtle">
                    Подключено {new Date(c.connected_at).toLocaleDateString()}
                  </div>
                </div>
                <button
                  onClick={() => revokeConnection.mutate(c.client_id)}
                  disabled={revokeConnection.isPending}
                  title="Отключить"
                  className="flex h-6 w-6 shrink-0 items-center justify-center text-subtle hover:text-danger disabled:opacity-50"
                >
                  <Trash2 size={13} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <details className="mt-3 rounded border px-3 py-2" onToggle={(e) => setAuditOpen(e.currentTarget.open)}>
        <summary className="cursor-pointer text-sm text-secondary">Что делали с базой</summary>
        <div className="mt-2 text-xs text-subtle">
          Действия внешних ассистентов за последние полгода. Содержимое заметок сюда не пишется —
          только что вызывали и когда.
        </div>
        {auditEntries === undefined && <div className="mt-2 text-xs text-subtle">Загрузка…</div>}
        {auditEntries?.length === 0 && (
          <div className="mt-2 text-xs text-subtle">Пока ничего не происходило</div>
        )}
        {auditEntries !== undefined && auditEntries.length > 0 && (
          <ul className="mt-2 max-h-60 space-y-0.5 overflow-y-auto">
            {auditEntries.map((e, i) => (
              <li key={i} className="flex items-baseline justify-between gap-3 text-xs">
                <span className="min-w-0 truncate text-secondary">
                  {AUDIT_LABELS[e.event] ?? e.event}
                  {e.subject && <span className="text-subtle"> · {e.subject}</span>}
                </span>
                <span className="shrink-0 tabular-nums text-subtle">
                  {new Date(e.created_at).toLocaleString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </details>

      <details className="mt-3 rounded border px-3 py-2">
        <summary className="cursor-pointer text-sm text-secondary">Как подключить — по шагам</summary>
        <div className="mt-3 space-y-3 text-xs text-secondary">
          <div>
            <div className="mb-1 font-medium text-primary">Claude Code (в терминале)</div>
            <ol className="list-decimal space-y-0.5 pl-4">
              <li>Создайте токен кнопкой ниже и скопируйте его.</li>
              <li>Выполните готовую команду — она появится рядом с токеном.</li>
              <li>Проверьте: <code className="rounded bg-muted-hover px-1">claude mcp list</code></li>
            </ol>
          </div>
          <div>
            <div className="mb-1 font-medium text-primary">claude.ai (веб и приложение)</div>
            <ol className="list-decimal space-y-0.5 pl-4">
              <li>Настройки → Коннекторы → добавить свой.</li>
              <li>
                Укажите адрес:{" "}
                <code className="break-all rounded bg-muted-hover px-1">{mcpUrl}</code>
              </li>
              <li>Войдите и нажмите «Разрешить» на экране согласия.</li>
            </ol>
            {/* Токен здесь не нужен — там свой поток входа. Люди пробуют
                вставить его туда и не понимают, почему не подходит. */}
            <div className="mt-1 text-subtle">Токен для этого не нужен — claude.ai попросит войти сам.</div>
          </div>
          <div>
            <div className="mb-1 font-medium text-primary">Что будет доступно</div>
            <p>
              Поиск и чтение заметок, списков, документов и напоминаний; создание и изменение.
              Зашифрованный сейф — никогда. Веб-поиск наружу не отдаётся: внешний ассистент ищет своим.
            </p>
          </div>
        </div>
      </details>
    </div>
  );
}

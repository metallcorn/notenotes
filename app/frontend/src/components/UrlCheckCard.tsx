import { useRef, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { ChevronDown, ChevronUp, KeyRound, Link2, RotateCw } from "lucide-react";
import { useRefreshUrlCheckWidget, useUrlCheckWidget } from "../api/hooks";
import { ExpandedTextPanel } from "./RecognizedTextView";
import Spinner from "./Spinner";

// Безопасный резолвер dot-path — "passportStatus.name" по
// {"passportStatus": {"name": "..."}} — отсутствующий/некорректный путь
// возвращает "—", а не бросает исключение и не роняет карточку.
function resolvePath(obj: unknown, path: string): string {
  let value: unknown = obj;
  for (const key of path.split(".")) {
    if (value === null || typeof value !== "object") return "—";
    value = (value as Record<string, unknown>)[key];
  }
  if (value === undefined || value === null) return "—";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function parseJsonSafe(text: string | null): unknown {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// Виджет «Проверить по ссылке» — вставляется только ассистентом
// (tools/url_check.py::insert_url_check_block, после того как пользователь
// в чате подтвердил предложенные поля). В content заметки лежит только id
// узла — реальное состояние (url/поля/заголовки авторизации/результат)
// живёт в url_check_widgets на бэкенде и подтягивается сюда при монтировании
// (useUrlCheckWidget), а «Обновить» (useRefreshUrlCheckWidget) обновляет
// ТОЛЬКО эту запись — ни content, ни Yjs, ни история версий не задеты.
export default function UrlCheckCard({ node }: NodeViewProps) {
  const { id } = node.attrs as { id: string | null };
  const [expanded, setExpanded] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const { data: widget, isLoading } = useUrlCheckWidget(id ?? undefined);
  const refresh = useRefreshUrlCheckWidget(id ?? undefined);

  if (!id) return null;

  if (isLoading || !widget) {
    return (
      <NodeViewWrapper as="div" className="my-1">
        <div className="max-w-md overflow-hidden rounded border bg-slate-50 px-3 py-2 text-xs text-slate-400">
          <Spinner size={12} className="mr-1 inline" /> Загрузка…
        </div>
      </NodeViewWrapper>
    );
  }

  const { url, fields, last_result: lastResult, last_fetched_at: lastFetchedAt, last_status: lastStatus, has_credentials: hasCredentials } = widget;
  const parsed = parseJsonSafe(lastResult);

  const domain = (() => {
    try {
      return new URL(url).hostname;
    } catch {
      return url;
    }
  })();

  const prettyJson = parsed !== null ? JSON.stringify(parsed, null, 2) : (lastResult ?? "");

  return (
    <NodeViewWrapper as="div" className="my-1">
      <div ref={cardRef} className="max-w-md overflow-hidden rounded border bg-slate-50">
        <div data-drag-handle draggable className="flex items-center gap-2 px-3 py-2">
          <Link2 size={16} className="shrink-0 text-slate-400" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1 truncate text-sm font-medium text-slate-800">
              {domain}
              {hasCredentials && (
                <span
                  title="Использует сохранённые заголовки авторизации — доступны всем с доступом к спейсу для этого запроса"
                  className="shrink-0"
                >
                  <KeyRound size={11} className="text-amber-500" aria-label="Использует сохранённую авторизацию" />
                </span>
              )}
            </div>
            <div className="truncate text-xs text-slate-400">
              {lastFetchedAt ? `Обновлено ${formatWhen(lastFetchedAt)}` : "Ещё не запрашивалось"}
              {lastStatus !== null && lastStatus >= 400 && <span className="ml-1 text-amber-600">(код {lastStatus})</span>}
            </div>
          </div>
          <button
            onClick={() => refresh.mutate()}
            disabled={refresh.isPending}
            title="Обновить"
            className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700 disabled:opacity-50"
          >
            {refresh.isPending ? <Spinner size={14} /> : <RotateCw size={14} />}
          </button>
        </div>

        {fields.length > 0 && parsed !== null && (
          <div className="space-y-1 border-t px-3 py-2 text-xs text-slate-700">
            {fields.map((f) => (
              <div key={f.path} className="flex items-center justify-between gap-2">
                <span className="text-slate-500">{f.label}</span>
                <span className="font-medium">{resolvePath(parsed, f.path)}</span>
              </div>
            ))}
          </div>
        )}

        {refresh.isError && <div className="border-t px-3 py-1.5 text-xs text-red-600">Не удалось обновить</div>}

        {lastResult && (
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex w-full items-center gap-1 border-t px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-100"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? "Скрыть сырой ответ" : "Показать сырой ответ"}
          </button>
        )}
        {lastResult && expanded && <ExpandedTextPanel anchorRef={cardRef} text={"```json\n" + prettyJson + "\n```"} />}
      </div>
    </NodeViewWrapper>
  );
}

import { useRef, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { ChevronDown, ChevronUp, Link2, RotateCw } from "lucide-react";
import { useCheckUrl } from "../api/hooks";
import { ExpandedTextPanel } from "./RecognizedTextView";
import Spinner from "./Spinner";

interface UrlCheckField {
  path: string;
  label: string;
}

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
// в чате подтвердил предложенные поля). Здесь только показ и «Обновить» —
// прямой REST-запрос (useCheckUrl), без ассистента: обновление данных не
// требует LLM.
export default function UrlCheckCard({ node, editor }: NodeViewProps) {
  const { url, fields: fieldsRaw, lastResult, lastFetchedAt, lastStatus } = node.attrs as {
    url: string;
    fields: string;
    lastResult: string | null;
    lastFetchedAt: string | null;
    lastStatus: number | null;
  };
  const [expanded, setExpanded] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const checkUrl = useCheckUrl();

  const fields = (parseJsonSafe(fieldsRaw) as UrlCheckField[] | null) ?? [];
  const parsed = parseJsonSafe(lastResult);

  const domain = (() => {
    try {
      return new URL(url).hostname;
    } catch {
      return url;
    }
  })();

  async function handleRefresh() {
    const result = await checkUrl.mutateAsync(url);
    editor
      .chain()
      .updateAttributes("urlCheck", {
        lastResult: result.error ? lastResult : (result.body ?? null),
        lastFetchedAt: result.error ? lastFetchedAt : new Date().toISOString(),
        lastStatus: result.error ? lastStatus : (result.status_code ?? null),
      })
      .run();
  }

  const prettyJson = parsed !== null ? JSON.stringify(parsed, null, 2) : (lastResult ?? "");

  return (
    <NodeViewWrapper as="div" className="my-1">
      <div ref={cardRef} className="max-w-md overflow-hidden rounded border bg-slate-50">
        <div data-drag-handle draggable className="flex items-center gap-2 px-3 py-2">
          <Link2 size={16} className="shrink-0 text-slate-400" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-slate-800">{domain}</div>
            <div className="truncate text-xs text-slate-400">
              {lastFetchedAt ? `Обновлено ${formatWhen(lastFetchedAt)}` : "Ещё не запрашивалось"}
              {lastStatus !== null && lastStatus >= 400 && <span className="ml-1 text-amber-600">(код {lastStatus})</span>}
            </div>
          </div>
          <button
            onClick={handleRefresh}
            disabled={checkUrl.isPending}
            title="Обновить"
            className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700 disabled:opacity-50"
          >
            {checkUrl.isPending ? <Spinner size={14} /> : <RotateCw size={14} />}
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

        {checkUrl.isError && <div className="border-t px-3 py-1.5 text-xs text-red-600">Не удалось обновить</div>}

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

import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { FileText } from "lucide-react";
import { api } from "../api/client";
import type { ItemTitleSearchResult } from "../api/types";

// Тот же список-с-клавиатурной-навигацией, что SlashMenuList.tsx, но
// результаты не статичные, а живой поиск по названию (routers/items.py::
// search_item_titles) — Suggestion (@tiptap/suggestion) вызывает items()
// СИНХРОННО, живого запроса внутри него не сделать, поэтому запрос и
// дебаунс — здесь, в самом компоненте, по props.query.
export interface NoteLinkSuggestionListHandle {
  onKeyDown: (props: { event: KeyboardEvent }) => boolean;
}

interface Props {
  query: string;
  command: (item: ItemTitleSearchResult) => void;
}

const DEBOUNCE_MS = 200;

const NoteLinkSuggestionList = forwardRef<NoteLinkSuggestionListHandle, Props>(({ query, command }, ref) => {
  const [results, setResults] = useState<ItemTitleSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(0);

  useEffect(() => {
    setSelected(0);
    if (!query.trim()) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const timer = setTimeout(() => {
      api
        .get<ItemTitleSearchResult[]>(`/items/search-titles?q=${encodeURIComponent(query)}`)
        .then((r) => setResults(r))
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  useImperativeHandle(ref, () => ({
    onKeyDown: ({ event }) => {
      if (event.key === "ArrowDown") {
        setSelected((i) => (results.length ? (i + 1) % results.length : 0));
        return true;
      }
      if (event.key === "ArrowUp") {
        setSelected((i) => (results.length ? (i - 1 + results.length) % results.length : 0));
        return true;
      }
      if (event.key === "Enter") {
        if (results[selected]) command(results[selected]);
        return true;
      }
      return false;
    },
  }));

  return (
    <div className="max-h-64 w-64 overflow-y-auto rounded border bg-white py-1 shadow-lg">
      {!query.trim() && <div className="px-3 py-2 text-xs text-slate-400">Начните вводить название заметки…</div>}
      {query.trim() && loading && <div className="px-3 py-2 text-xs text-slate-400">Ищем…</div>}
      {query.trim() && !loading && results.length === 0 && (
        <div className="px-3 py-2 text-xs text-slate-400">Ничего не найдено</div>
      )}
      {results.map((item, i) => (
        <button
          key={item.id}
          onClick={() => command(item)}
          className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm ${i === selected ? "bg-violet-50 text-violet-700" : "text-slate-700 hover:bg-slate-50"}`}
        >
          <FileText size={14} className="shrink-0 text-slate-400" />
          <span className="truncate">{item.title || "Без названия"}</span>
        </button>
      ))}
    </div>
  );
});
NoteLinkSuggestionList.displayName = "NoteLinkSuggestionList";

export default NoteLinkSuggestionList;

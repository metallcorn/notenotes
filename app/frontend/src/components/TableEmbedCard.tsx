import { useEffect, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { useSearchParams } from "react-router-dom";
import { ExternalLink, Table as TableIcon, Unlink } from "lucide-react";
import { useTable, useUpdateItem } from "../api/hooks";
import Spinner from "./Spinner";
import TableGrid from "./TableGrid";

// Карточка встроенной rich-таблицы — живой TableGrid прямо в тексте
// заметки. tableId только СВЯЗЫВАЕТ узел с существующим item'ом (см.
// комментарий в TableEmbed.ts): удаление узла не удаляет саму таблицу, и
// удаление самой таблицы (в другом месте) не должно ронять эту заметку —
// отсюда ветка isError ниже.
export default function TableEmbedCard({ node, editor, getPos }: NodeViewProps) {
  const { tableId } = node.attrs as { tableId: string };
  const { data: table, isLoading, isError } = useTable(tableId);
  const updateItem = useUpdateItem();
  const [, setSearchParams] = useSearchParams();

  const [title, setTitle] = useState("");
  const [syncedId, setSyncedId] = useState<string | null>(null);

  useEffect(() => {
    if (table && syncedId !== table.id) {
      setTitle(table.title);
      setSyncedId(table.id);
    }
  }, [table, syncedId]);

  function saveTitle() {
    if (table && title.trim() && title !== table.title) {
      updateItem.mutate({ id: table.id, title: title.trim() });
    }
  }

  function unlink() {
    const pos = typeof getPos === "function" ? getPos() : null;
    if (pos === null || pos === undefined) return;
    editor.chain().focus().deleteRange({ from: pos, to: pos + node.nodeSize }).run();
  }

  if (isError) {
    return (
      <NodeViewWrapper as="div" className="my-1">
        <div className="max-w-md rounded border border-dashed bg-slate-50 px-3 py-2 text-sm text-slate-400">
          Таблица удалена или недоступна
        </div>
      </NodeViewWrapper>
    );
  }

  if (isLoading || !table) {
    return (
      <NodeViewWrapper as="div" className="my-1">
        <div className="flex max-w-md items-center justify-center rounded border bg-slate-50 px-3 py-4">
          <Spinner size={16} />
        </div>
      </NodeViewWrapper>
    );
  }

  return (
    <NodeViewWrapper as="div" className="my-1">
      <div data-testid="table-embed-card" className="overflow-hidden rounded border bg-white">
        <div data-drag-handle draggable className="flex items-center gap-2 border-b bg-slate-50 px-3 py-2">
          <TableIcon size={15} className="shrink-0 text-slate-400" />
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={saveTitle}
            onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()}
            placeholder="Название таблицы"
            className="min-w-0 flex-1 truncate border-none bg-transparent text-sm font-medium text-slate-900 outline-none"
          />
          <button
            onClick={() => setSearchParams({ item: table.id })}
            title="Открыть как отдельную страницу"
            className="flex h-7 w-7 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700"
          >
            <ExternalLink size={14} />
          </button>
          <button
            onClick={unlink}
            title="Отвязать от заметки (сама таблица не удалится)"
            className="flex h-7 w-7 shrink-0 items-center justify-center text-slate-400 hover:text-red-600"
          >
            <Unlink size={14} />
          </button>
        </div>
        <div className="p-3">
          <TableGrid tableId={tableId} />
        </div>
      </div>
    </NodeViewWrapper>
  );
}

import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import Spinner from "./Spinner";

export default function UploadPlaceholderCard({ node }: NodeViewProps) {
  const { filename } = node.attrs as { filename?: string };
  return (
    <NodeViewWrapper as="div" className="my-1">
      <div className="flex items-center gap-2 rounded border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-500">
        <Spinner size={16} />
        <span className="truncate">Загружается{filename ? `: ${filename}` : "…"}</span>
      </div>
    </NodeViewWrapper>
  );
}

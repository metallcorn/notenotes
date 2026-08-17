import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { Globe } from "lucide-react";
import { useLinkPreview } from "../api/hooks";

// Богатая карточка — linkPreview всегда блочный atom-узел
// (extensions/LinkPreview.ts, group: "block"), у него физически не бывает
// текста слева/справа на той же строке — только соседние абзацы
// сверху/снизу, которые к самой карточке отношения не имеют. Картинка/
// описание поэтому видны сразу, без наведения — не нужно наводить курсор
// на каждую ссылку в списке по очереди, чтобы понять, что там.
function RichCard({ url, favicon, title, imageUrl, description }: {
  url: string; favicon: string | null; title: string; imageUrl: string | null; description: string;
}) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex max-w-md overflow-hidden rounded border bg-slate-50 text-sm text-slate-800 no-underline hover:bg-slate-100"
    >
      {imageUrl && <img src={imageUrl} alt="" className="h-24 w-24 shrink-0 object-cover" />}
      <div className="min-w-0 flex-1 p-2">
        <div className="mb-1 flex items-center gap-1.5">
          {favicon ? (
            <img
              src={favicon}
              alt=""
              className="h-3.5 w-3.5 shrink-0"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            <Globe size={12} className="shrink-0 text-slate-400" />
          )}
          <span className="truncate font-medium">{title}</span>
        </div>
        {description && <div className="line-clamp-2 text-xs text-slate-600">{description}</div>}
      </div>
    </a>
  );
}

export default function LinkPreviewCard({ node }: NodeViewProps) {
  const url = node.attrs.url as string;
  const { data, isLoading } = useLinkPreview(url);

  // Пока грузится или карточку не удалось собрать (сайт не ответил,
  // заблокирован SSRF-проверкой и т.п.) — обычная синяя ссылка, не
  // заглушка/скелетон.
  if (isLoading || !data || data.fetch_failed || !data.title) {
    return (
      <NodeViewWrapper as="div" className="my-1">
        <a href={url} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">
          {url}
        </a>
      </NodeViewWrapper>
    );
  }

  return (
    <NodeViewWrapper as="div" className="my-1" data-drag-handle draggable>
      <RichCard
        url={url}
        favicon={data.favicon_url}
        title={data.title}
        imageUrl={data.image_url}
        description={data.description || ""}
      />
    </NodeViewWrapper>
  );
}

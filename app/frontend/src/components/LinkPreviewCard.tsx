import { useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { Globe } from "lucide-react";
import { useLinkPreview } from "../api/hooks";

// Ховер-попап рендерится через портал в document.body с координатами от
// самой карточки, а не обычным position: absolute внутри редактора —
// редактор сам overflow-y-auto контейнер (плюс может быть внутри панели с
// overflow-x-auto), и абсолютно спозиционированный попап обрезался бы по
// его границам. Тот же баг и то же решение, что у AiMenu (кнопка ИИ на
// панели инструментов, реальная жалоба "кнопка не работает" — на самом
// деле выпадающее меню было невидимо из-за обрезки).
function HoverPopover({ anchor, imageUrl, description }: { anchor: HTMLElement; imageUrl: string | null; description: string }) {
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);

  useLayoutEffect(() => {
    const rect = anchor.getBoundingClientRect();
    setPosition({ top: rect.bottom + 4, left: rect.left });
  }, [anchor]);

  if (!position) return null;

  return createPortal(
    <div
      style={{ top: position.top, left: position.left }}
      className="fixed z-50 w-72 overflow-hidden rounded border bg-white shadow-lg"
    >
      {imageUrl && <img src={imageUrl} alt="" className="h-32 w-full object-cover" />}
      {description && <div className="p-2 text-xs text-slate-600">{description}</div>}
    </div>,
    document.body,
  );
}

export default function LinkPreviewCard({ node }: NodeViewProps) {
  const url = node.attrs.url as string;
  const { data, isLoading } = useLinkPreview(url);
  const [hovered, setHovered] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

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

  const hasHoverContent = !!(data.image_url || data.description);

  return (
    <NodeViewWrapper as="div" className="my-1" data-drag-handle draggable>
      <div
        ref={cardRef}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        className="relative inline-block"
      >
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex max-w-full items-center gap-2 rounded border bg-slate-50 px-3 py-2 text-sm text-slate-800 no-underline hover:bg-slate-100"
        >
          {data.favicon_url ? (
            <img
              src={data.favicon_url}
              alt=""
              className="h-4 w-4 shrink-0"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            <Globe size={14} className="shrink-0 text-slate-400" />
          )}
          <span className="truncate font-medium">{data.title}</span>
        </a>
        {hovered && hasHoverContent && cardRef.current && (
          <HoverPopover anchor={cardRef.current} imageUrl={data.image_url} description={data.description || ""} />
        )}
      </div>
    </NodeViewWrapper>
  );
}

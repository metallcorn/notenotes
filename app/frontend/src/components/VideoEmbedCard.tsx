import { NodeViewWrapper } from "@tiptap/react";
import type { EmbedInfo } from "../lib/embedPlatforms";

// iframe сам по себе кликабелен только внутри своей области — в отличие от
// RichCard (LinkPreviewCard.tsx) тут нет обёртки-<a> на всю карточку, так
// что баг "draggable на узле с <a> внутри открывает две вкладки" (см.
// комментарий в LinkPreview.ts) сюда не относится.
export default function VideoEmbedCard({ url, embed }: { url: string; embed: EmbedInfo }) {
  return (
    <NodeViewWrapper as="div" className="my-1">
      <div className="max-w-xl overflow-hidden rounded border bg-black">
        <div className="relative aspect-video">
          <iframe
            src={embed.embedUrl}
            title={url}
            className="absolute inset-0 h-full w-full"
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
            allowFullScreen
            loading="lazy"
          />
        </div>
      </div>
    </NodeViewWrapper>
  );
}

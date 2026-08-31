import { useState, type CSSProperties } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { formatBytes } from "../lib/format";

// Реальная просьба: ширина видео регулируется как у картинки
// (VideoToolbar.tsx), и до загрузки/воспроизведения видно, сколько файл
// весит — оверлей с весом гаснет сам, как только запустили плеер, чтобы
// не мешать управлению.
export default function VideoView({ node }: NodeViewProps) {
  const { src, width, size } = node.attrs as { src: string; width?: string | null; size?: number | null };
  const [playing, setPlaying] = useState(false);

  const wrapperStyle: CSSProperties = { width: width || "100%" };

  return (
    <NodeViewWrapper as="div" data-drag-handle draggable className="my-1 max-w-full">
      <div className="relative inline-block max-w-full" style={wrapperStyle}>
        <video
          src={src}
          controls
          preload="metadata"
          className="block max-h-[70vh] w-full rounded"
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
        />
        {!!size && !playing && (
          <div className="pointer-events-none absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-xs font-medium text-white">
            {formatBytes(size)}
          </div>
        )}
      </div>
    </NodeViewWrapper>
  );
}

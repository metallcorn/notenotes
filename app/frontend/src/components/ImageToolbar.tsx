import { useState } from "react";
import type { Editor } from "@tiptap/core";
import { Expand, RotateCw, Sparkles } from "lucide-react";
import { useReprocessUpload } from "../api/hooks";
import ImageLightbox from "./ImageLightbox";
import Spinner from "./Spinner";

// 0 -> 90 -> 180 -> 270 -> 0, как в Telegram — только прямые углы, ничего
// произвольного. Хранится в самом узле (rotation в ResizableImage.ts) —
// реальная жалоба: телефон снял горизонтально, в заметке читать
// невозможно, разворот должен СОХРАНЯТЬСЯ, а не сбрасываться при
// перезагрузке (в отличие от разворота в ImageLightbox.tsx — тот только
// для текущего просмотра, там сохранять нечего и незачем).
const NEXT_ROTATION: Record<number, number> = { 0: 90, 90: 180, 180: 270, 270: 0 };

const WIDTHS = [
  { label: "Маленькая", value: "25%" },
  { label: "Средняя", value: "50%" },
  { label: "Крупная", value: "75%" },
];

const ALIGNS: { label: string; value: "left" | "center" | "right" }[] = [
  { label: "Слева", value: "left" },
  { label: "По центру", value: "center" },
  { label: "Справа", value: "right" },
];

export default function ImageToolbar({ editor }: { editor: Editor }) {
  const [lightbox, setLightbox] = useState(false);
  const attrs = editor.getAttributes("image") as {
    src?: string;
    alt?: string | null;
    width?: string | null;
    align?: string | null;
    rotation?: number;
  };
  const reprocess = useReprocessUpload();

  function setAttrs(patch: Record<string, string | number | null>) {
    editor.chain().focus().updateAttributes("image", patch).run();
  }

  function rotate() {
    setAttrs({ rotation: NEXT_ROTATION[attrs.rotation ?? 0] ?? 90 });
  }

  // /api/uploads/{id} -> id. Картинки, вставленные не через загрузчик
  // (вставка по внешней ссылке), этого id не имеют — для них кнопки нет.
  const uploadId = attrs.src?.match(/\/api\/uploads\/([0-9a-f-]+)/)?.[1] ?? null;

  async function handleReprocess() {
    if (!uploadId) return;
    const { to } = editor.state.selection;
    editor
      .chain()
      .focus()
      .insertContentAt(to, { type: "paragraph", content: [{ type: "text", text: `⏳ Описание изображения ${uploadId} обрабатывается…` }] })
      .run();
    await reprocess.mutateAsync(uploadId);
  }

  return (
    <>
      <div className="mx-4 mb-1 flex flex-wrap items-center gap-2 rounded-2xl bg-brand-soft px-3 py-1.5 text-xs font-bold text-brand-text">
        <span>Картинка:</span>
        <button
          onClick={() => setLightbox(true)}
          title="Открыть в полный размер"
          className="flex h-7 items-center gap-1 rounded-full bg-surface px-2.5 text-secondary hover:bg-muted"
        >
          <Expand size={14} />
          Открыть
        </button>
        <button
          onClick={rotate}
          title="Повернуть на 90°"
          className="flex h-7 items-center gap-1 rounded-full bg-surface px-2.5 text-secondary hover:bg-muted"
        >
          <RotateCw size={14} />
          Повернуть
        </button>
        {uploadId && (
          <button
            onClick={handleReprocess}
            disabled={reprocess.isPending}
            title="Заново распознать текст/описание на картинке через ИИ"
            className="flex items-center gap-1 rounded bg-surface px-1.5 py-0.5 text-brand hover:bg-brand/10 disabled:opacity-50"
          >
            {reprocess.isPending ? <Spinner size={12} /> : <Sparkles size={14} />}
            Обработать заново
          </button>
        )}
        <div className="flex gap-0.5">
          {WIDTHS.map((w) => (
            <button
              key={w.value}
              onClick={() => setAttrs({ width: attrs.width === w.value ? null : w.value })}
              className={`rounded px-1.5 py-0.5 ${
                attrs.width === w.value ? "bg-accent text-on-accent" : "bg-surface text-secondary hover:bg-muted-hover"
              }`}
            >
              {w.label}
            </button>
          ))}
          <button
            onClick={() => setAttrs({ width: null })}
            className={`rounded px-1.5 py-0.5 ${
              !attrs.width ? "bg-accent text-on-accent" : "bg-surface text-secondary hover:bg-muted-hover"
            }`}
          >
            Оригинал
          </button>
        </div>
        <div className="flex gap-0.5">
          {ALIGNS.map((a) => (
            <button
              key={a.value}
              onClick={() => setAttrs({ align: attrs.align === a.value ? null : a.value })}
              className={`rounded px-1.5 py-0.5 ${
                attrs.align === a.value ? "bg-accent text-on-accent" : "bg-surface text-secondary hover:bg-muted-hover"
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>
      {lightbox && attrs.src && (
        <ImageLightbox
          images={[{ src: attrs.src, alt: attrs.alt ?? undefined }]}
          onClose={() => setLightbox(false)}
        />
      )}
    </>
  );
}

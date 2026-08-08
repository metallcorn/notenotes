import { useState } from "react";
import type { Editor } from "@tiptap/core";
import { Expand, Sparkles } from "lucide-react";
import { useReprocessUpload } from "../api/hooks";
import ImageLightbox from "./ImageLightbox";
import Spinner from "./Spinner";

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
  const attrs = editor.getAttributes("image") as { src?: string; alt?: string | null; width?: string | null; align?: string | null };
  const reprocess = useReprocessUpload();

  function setAttrs(patch: Record<string, string | null>) {
    editor.chain().focus().updateAttributes("image", patch).run();
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
      .insertContentAt(to, { type: "paragraph", content: [{ type: "text", text: `[Описание изображения ${uploadId} обрабатывается…]` }] })
      .run();
    await reprocess.mutateAsync(uploadId);
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 border-b bg-amber-50 px-3 py-1.5 text-xs">
        <span className="text-slate-500">Картинка:</span>
        <button
          onClick={() => setLightbox(true)}
          title="Открыть в полный размер"
          className="flex items-center gap-1 rounded bg-white px-1.5 py-0.5 text-slate-600 hover:bg-slate-100"
        >
          <Expand size={14} />
          Открыть
        </button>
        {uploadId && (
          <button
            onClick={handleReprocess}
            disabled={reprocess.isPending}
            title="Заново распознать текст/описание на картинке через ИИ"
            className="flex items-center gap-1 rounded bg-white px-1.5 py-0.5 text-violet-600 hover:bg-violet-50 disabled:opacity-50"
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
                attrs.width === w.value ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100"
              }`}
            >
              {w.label}
            </button>
          ))}
          <button
            onClick={() => setAttrs({ width: null })}
            className={`rounded px-1.5 py-0.5 ${
              !attrs.width ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100"
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
                attrs.align === a.value ? "bg-slate-900 text-white" : "bg-white text-slate-600 hover:bg-slate-100"
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

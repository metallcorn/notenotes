import { useRef, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

// Общий рендер распознанного текста (OCR картинки — vision.py, PDF —
// pdf_processing.py) — раньше показывался ПЛОСКИМ текстом в обеих
// карточках (DocumentAttachmentCard и ImageOcrResultCard), хотя промпт
// распознавания уже отдаёт заголовки/таблицы/списки. Один общий модуль,
// не копия в каждой карточке — тот же текстовый формат, тот же спойлер.
export const recognizedTextMarkdownComponents: Components = {
  h1: (props) => <h3 className="mb-1 mt-2 text-sm font-semibold first:mt-0" {...props} />,
  h2: (props) => <h4 className="mb-1 mt-2 text-sm font-semibold first:mt-0" {...props} />,
  h3: (props) => <h5 className="mb-1 mt-2 text-xs font-semibold first:mt-0" {...props} />,
  p: (props) => <p className="mb-1.5 last:mb-0" {...props} />,
  ul: (props) => <ul className="mb-1.5 list-disc pl-4 last:mb-0" {...props} />,
  ol: (props) => <ol className="mb-1.5 list-decimal pl-4 last:mb-0" {...props} />,
  table: (props) => (
    <div className="mb-1.5 overflow-x-auto">
      <table className="border-collapse text-xs" {...props} />
    </div>
  ),
  th: (props) => <th className="border border-slate-300 bg-slate-100 px-1.5 py-1 text-left font-medium" {...props} />,
  td: (props) => <td className="border border-slate-300 px-1.5 py-1" {...props} />,
  code: (props) => <code className="rounded bg-slate-100 px-1 py-0.5 text-[11px]" {...props} />,
  pre: (props) => <pre className="mb-1.5 overflow-x-auto rounded bg-slate-100 p-2 text-[11px] last:mb-0" {...props} />,
  a: ({ node: _node, ...props }) => (
    <a {...props} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline" />
  ),
};

// "Скопировать форматированным"/"как MD" — общие кнопки для обеих карточек
// распознанного текста. Скрытый ReactMarkdown ниже — источник HTML для
// форматированной копии (вставка в Docs/Word/Notion сохранит разметку),
// не завязан на то, развёрнут ли спойлер сейчас.
export function RecognizedTextCopyButtons({ text }: { text: string }) {
  const [copiedKind, setCopiedKind] = useState<"formatted" | "md" | null>(null);
  const hiddenMdRef = useRef<HTMLDivElement>(null);

  async function copyFormatted() {
    try {
      const html = hiddenMdRef.current?.innerHTML ?? "";
      await navigator.clipboard.write([
        new ClipboardItem({
          "text/html": new Blob([html], { type: "text/html" }),
          "text/plain": new Blob([text], { type: "text/plain" }),
        }),
      ]);
    } catch {
      // Старые браузеры без ClipboardItem/text-html — хотя бы сырой текст.
      await navigator.clipboard.writeText(text);
    }
    setCopiedKind("formatted");
    setTimeout(() => setCopiedKind(null), 1500);
  }

  async function copyMarkdown() {
    await navigator.clipboard.writeText(text);
    setCopiedKind("md");
    setTimeout(() => setCopiedKind(null), 1500);
  }

  return (
    <>
      <button
        type="button"
        onClick={copyFormatted}
        title="Скопировать форматированным (для Docs/Word/Notion)"
        className="flex h-9 w-9 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700"
      >
        {copiedKind === "formatted" ? <Check size={14} className="text-emerald-600" /> : <Copy size={14} />}
      </button>
      <button
        type="button"
        onClick={copyMarkdown}
        title="Скопировать как Markdown"
        className="flex h-9 shrink-0 items-center justify-center px-2 text-[10px] font-medium text-slate-400 hover:text-slate-700"
      >
        {copiedKind === "md" ? <Check size={14} className="text-emerald-600" /> : "MD"}
      </button>
      <div ref={hiddenMdRef} className="hidden">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={recognizedTextMarkdownComponents}>
          {text}
        </ReactMarkdown>
      </div>
    </>
  );
}

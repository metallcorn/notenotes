import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
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

// Реальная жалоба, повторявшаяся много раз подряд несмотря на несколько
// разных попыток фикса (stopPropagation, -webkit-user-drag, scoping
// data-drag-handle/draggable): выделить текст мышью внутри спойлера
// упорно не получалось — карточка (ProseMirror atom-узел) всё равно
// перехватывала жест как перетаскивание. Причина глубже, чем любая
// точечная правка: NodeView.stopEvent у @tiptap/core в принципе
// перехватывает mousedown внутри ЛЮБОГО потомка узла, если этот узел
// selectable (см. исходники — even без data-drag-handle рядом, клик по
// selectable atom-узлу может стать NodeSelection). Вместо дальнейших
// попыток обыграть эту логику изнутри — спойлер рендерится ПОРТАЛОМ в
// document.body, ВНЕ DOM-дерева редактора целиком (тот же приём, что уже
// использует ThumbnailPopover в DocumentAttachmentCard.tsx для превью по
// ховеру). Раз DOM физически не является потомком узла — ProseMirror
// вообще не видит эти события, и они работают как обычный HTML: выделение
// текста мышью, копирование — без чего-либо специального.
interface PanelPosition {
  top?: number;
  bottom?: number;
  left: number;
  width: number;
  maxHeight: number;
}

// Комфортная высота панели — под неё стараемся освободить место прокруткой,
// прежде чем смириться с ужатой панелью.
const DESIRED_PANEL_HEIGHT = 300;

export function ExpandedTextPanel({ anchorRef, text }: { anchorRef: React.RefObject<HTMLElement>; text: string }) {
  const [pos, setPos] = useState<PanelPosition | null>(null);
  const scrolledRef = useRef(false);

  useEffect(() => {
    // Реальная жалоба: панель — fixed-position портал в document.body (см.
    // докстринг ниже), она НЕ участвует в потоке страницы — раньше всегда
    // открывалась ВНИЗ от якоря фиксированной высотой (max-h-96) без учёта
    // реального свободного места. Первый фикс просто УЖИМАЛ панель под
    // огрызок свободного места — технически не вылезает за экран, но
    // читать в маленьком окошке неудобно. Реальный лучший вариант — ДВИГАТЬ
    // СТРАНИЦУ: один раз при открытии докручиваем (scrollIntoView сама
    // находит нужный прокручиваемый контейнер — им может быть как окно,
    // так и сам редактор, у него тоже overflow-y-auto) так, чтобы под
    // якорем стало ДОСТАТОЧНО места, и только если его действительно не
    // хватает ни сверху, ни снизу. Ужатие остаётся запасным вариантом на
    // случай совсем маленьких экранов, где даже после прокрутки места
    // объективно больше не становится.
    function update() {
      if (!anchorRef.current) return;
      const r = anchorRef.current.getBoundingClientRect();
      const margin = 8;
      const width = Math.max(r.width, 240);

      const maxLeft = window.innerWidth - width - margin;
      const left = Math.max(margin, Math.min(r.left, maxLeft));

      const spaceBelow = window.innerHeight - r.bottom - margin;
      const spaceAbove = r.top - margin;

      if (!scrolledRef.current && spaceBelow < DESIRED_PANEL_HEIGHT && spaceAbove < DESIRED_PANEL_HEIGHT) {
        scrolledRef.current = true;
        anchorRef.current.scrollIntoView({ behavior: "smooth", block: "start" });
        return; // scroll-листенер ниже перезапустит update(), когда докрутится
      }

      // Реальный найденный баг предыдущей версии этого фикса: Math.max(120, …)
      // ниже навязывал МИНИМАЛЬНУЮ высоту 120px, даже когда реального места
      // было меньше (например, 90px) — то есть панель всё равно вылезала за
      // край ровно на разницу, то же самое, что чинили. Клэмпить — значит
      // ТОЛЬКО ограничивать сверху, никогда не раздувать сверх доступного —
      // никакого искусственного минимума; если места мало с обеих сторон
      // даже после прокрутки, короткая панель со своим скроллом — ожидаемый
      // запасной исход, не баг. Math.max(0, …) — защита от отрицательного
      // значения, если сам якорь уже частично за пределами экрана.
      if (spaceBelow >= 160 || spaceBelow >= spaceAbove) {
        setPos({ top: r.bottom + 4, left, width, maxHeight: Math.min(384, Math.max(0, spaceBelow)) });
      } else {
        setPos({ bottom: window.innerHeight - r.top + 4, left, width, maxHeight: Math.min(384, Math.max(0, spaceAbove)) });
      }
    }
    update();
    // capture: true — ловит скролл ЛЮБОГО предка-контейнера (сам редактор
    // тоже overflow-y-auto), не только окна целиком.
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [anchorRef]);

  if (!pos) return null;

  return createPortal(
    <div
      style={{ top: pos.top, bottom: pos.bottom, left: pos.left, width: pos.width, maxHeight: pos.maxHeight }}
      className="fixed z-40 overflow-y-auto rounded border bg-white p-3 text-xs text-slate-700 shadow-lg"
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={recognizedTextMarkdownComponents}>
        {text}
      </ReactMarkdown>
    </div>,
    document.body,
  );
}

import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import ImageOcrResultCard from "../components/ImageOcrResultCard";

// Реальный запрос: распознанный текст картинки (vision.py) раньше вставлялся
// голым абзацем прямо в заметку — засоряет её, особенно у картинок с
// таблицами/длинным текстом (скриншоты приложений). Тот же спойлер-приём,
// что уже есть у распознанного текста PDF (DocumentAttachment.ts) — просто
// свёрнутая кнопка вместо простыни текста, сама картинка (обычный <img>,
// не трогали) остаётся видна сразу как есть. Отдельный узел, а не
// прикрученный к самой картинке: vision.py умеет только строковую замену
// плейсхолдера на новый текст (не умеет лезть внутрь атрибутов уже
// вставленного узла) — плейсхолдер как стоял отдельным абзацем после
// картинки, так и превращается в этот узел на том же месте, без изменений
// в insertImage() на фронте вообще.
// uploadId/canReprocess — см. app/backend/app/vision.py::serialize_image_ocr_result:
// раньше карточка не знала, из какого upload она получена, поэтому не было
// ни кнопки "распознать заново", ни ручной правки текста при ошибке OCR.
export function serializeImageOcrResult(uploadId: string, text: string, canReprocess = false): string {
  const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/\n/g, "&#10;").replace(/"/g, "&quot;");
  const reprocessAttr = canReprocess ? ' data-can-reprocess="1"' : "";
  return `<div data-image-ocr-result data-text="${esc(text)}" data-upload-id="${uploadId}"${reprocessAttr}></div>`;
}

export const ImageOcrResult = Node.create({
  name: "imageOcrResult",
  group: "block",
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      text: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-text") ?? "",
        renderHTML: (attrs: { text?: string }) => (attrs.text ? { "data-text": attrs.text } : {}),
      },
      uploadId: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-upload-id"),
        renderHTML: (attrs: { uploadId?: string | null }) => (attrs.uploadId ? { "data-upload-id": attrs.uploadId } : {}),
      },
      canReprocess: {
        default: false,
        parseHTML: (element: HTMLElement) => element.hasAttribute("data-can-reprocess"),
        renderHTML: (attrs: { canReprocess?: boolean }) => (attrs.canReprocess ? { "data-can-reprocess": "1" } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-image-ocr-result]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-image-ocr-result": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ImageOcrResultCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void; closeBlock: (node: unknown) => void },
          node: { attrs: { text: string; uploadId: string | null; canReprocess: boolean } },
        ) {
          state.write(serializeImageOcrResult(node.attrs.uploadId ?? "", node.attrs.text, node.attrs.canReprocess));
          state.closeBlock(node);
        },
        parse: {},
      },
    };
  },
});

import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import UploadPlaceholderCard from "../components/UploadPlaceholderCard";

// Реальная жалоба: перетащил/выбрал PDF — на холсте ничего не появлялось,
// пока не завершится вся загрузка+обработка на сервере ("не моментально,
// а с большой задержкой"), хотя сама передача файла по сети — это и есть
// основное время ожидания (см. NoteEditor.tsx::uploadAndInsertFiles).
// Этот узел — временная карточка "Загружается…", вставляется СРАЗУ, ещё до
// начала запроса на сервер, и заменяется на настоящий узел (картинка/
// видео/аудио/documentAttachment) по готовности — по tempId, а не по
// запомненной позиции (за время await пользователь мог напечатать что-то
// ещё, позиции сместились бы).
//
// Транзиентный узел: не должен переживать сохранение, если пользователь
// закрыл вкладку посреди загрузки — иначе после перезагрузки в заметке
// остался бы вечный "призрак" с крутящимся спиннером, который никогда не
// заменится (запрос на загрузку прерван вместе с вкладкой). Сериализуется
// в пустоту — просто исчезает при следующем открытии.
export const UploadPlaceholder = Node.create({
  name: "uploadPlaceholder",
  group: "block",
  atom: true,

  addAttributes() {
    return {
      tempId: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-temp-id"),
        renderHTML: (attrs: { tempId?: string | null }) => (attrs.tempId ? { "data-temp-id": attrs.tempId } : {}),
      },
      filename: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-filename") ?? "",
        renderHTML: (attrs: { filename?: string }) => (attrs.filename ? { "data-filename": attrs.filename } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "div[data-upload-placeholder]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["div", mergeAttributes(HTMLAttributes, { "data-upload-placeholder": "" })];
  },

  addNodeView() {
    return ReactNodeViewRenderer(UploadPlaceholderCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize() {
          // Нарочно ничего не пишет — см. комментарий выше.
        },
        parse: {},
      },
    };
  },
});

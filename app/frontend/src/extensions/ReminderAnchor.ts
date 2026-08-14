import { Node, mergeAttributes } from "@tiptap/core";
import { ReactNodeViewRenderer } from "@tiptap/react";
import ReminderAnchorCard from "../components/ReminderAnchorCard";

// Реальная жалоба: напоминание, поставленное из конкретной строки заметки
// (/напом), должно возвращать ИМЕННО СЮДА по клику, не просто открывать
// заметку целиком — "я же не просто так его ставлю, а как якорь". Маленький
// инлайн-атом с id самого уведомления (не отдельный сгенерированный id —
// напоминание и так уже получает реальный id от бэкенда после создания,
// незачем городить второй). NoteEditor.tsx ищет по этому data-атрибуту и
// скроллит/подсвечивает при переходе из центра уведомлений — тот же приём,
// что уже есть у пунктов списка (ListEditor.tsx, highlightEntryId).
//
// Второй реальный найденный пробел: голая иконка ⏰ без подписи — "я же
// создаю алерт, его имя должно отображаться, иначе зачем оно мне". title
// сохраняется прямо в атрибуте узла (известен в момент создания, не нужно
// ходить за ним отдельно) — а живой статус (сработало/выполнено/ждёт)
// рисует ReminderAnchorCard.tsx через ReactNodeView, сверяясь со списком
// уведомлений при каждом рендере, а не застывшей на момент вставки картинкой
// — иначе после выполнения напоминания иконка так и висела бы как ни в чём
// не бывало.
export const ReminderAnchor = Node.create({
  name: "reminderAnchor",
  group: "inline",
  inline: true,
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      notificationId: {
        default: null,
        parseHTML: (element: HTMLElement) => element.getAttribute("data-reminder-id"),
        renderHTML: (attrs: { notificationId?: string | null }) =>
          attrs.notificationId ? { "data-reminder-id": attrs.notificationId } : {},
      },
      title: {
        default: "",
        parseHTML: (element: HTMLElement) => element.getAttribute("data-reminder-title") ?? "",
        renderHTML: (attrs: { title?: string }) => (attrs.title ? { "data-reminder-title": attrs.title } : {}),
      },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-reminder-anchor]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return ["span", mergeAttributes(HTMLAttributes, { "data-reminder-anchor": "", class: "reminder-anchor" }), "⏰"];
  },

  addNodeView() {
    return ReactNodeViewRenderer(ReminderAnchorCard);
  },

  addStorage() {
    return {
      markdown: {
        serialize(
          state: { write: (s: string) => void },
          node: { attrs: { notificationId: string | null; title: string } },
        ) {
          const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
          const titleAttr = node.attrs.title ? ` data-reminder-title="${esc(node.attrs.title)}"` : "";
          state.write(`<span data-reminder-anchor data-reminder-id="${node.attrs.notificationId ?? ""}"${titleAttr}>⏰</span>`);
        },
        parse: {},
      },
    };
  },
});

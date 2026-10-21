import type { MessageKey } from "./ru";

// Record по ключам ru: забытый перевод — ошибка сборки, а не русская
// строка, тихо всплывшая в английском интерфейсе.
export const en: Record<MessageKey, string> = {
  "nav.assistant": "Assistant",
  "nav.activity": "Activity",
  "nav.documents": "Documents",
  "nav.trash": "Trash",
};

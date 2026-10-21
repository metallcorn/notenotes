import { dateLocale } from "../i18n";

export interface NoteTemplate {
  id: string;
  label: string;
  title: string;
  content: string;
}

// Шаблоны — просто стартовая Markdown-структура, ничего не навязывают:
// пользователь может стереть и переписать как угодно (ТЗ — формат всегда
// Markdown вне зависимости от режима редактирования). Общие для шапки
// списка заметок (NoteList) и шторки «Создать» (CreateSheet).
export const NOTE_TEMPLATES: NoteTemplate[] = [
  { id: "blank", label: "Пустая заметка", title: "", content: "" },
  {
    id: "meeting",
    label: "Встреча",
    title: "Встреча",
    content: "**Дата:** \n**Участники:** \n\n## Повестка\n\n\n## Итоги и задачи\n\n",
  },
  {
    id: "diary",
    label: "Дневник",
    title: new Date().toLocaleDateString(dateLocale),
    content: "",
  },
  {
    id: "idea",
    label: "Идея",
    title: "",
    content: "## Проблема\n\n\n## Решение\n\n\n## Следующие шаги\n\n",
  },
];

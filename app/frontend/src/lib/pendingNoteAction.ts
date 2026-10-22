// Действие, которое редактор должен выполнить сразу после открытия только
// что созданной заметки: шторка «Создать» (макет «Кнопка +», 21.10)
// предлагает «Голосом», «Скан / фото», «Файл» — это обычная заметка плюс
// первый шаг внутри неё. Хранится в памяти вкладки по id заметки и
// забирается ровно один раз; перезагрузку не переживает намеренно.
export type PendingNoteAction = "record" | "photo" | "file";

const pending = new Map<string, PendingNoteAction>();

export function setPendingNoteAction(itemId: string, action: PendingNoteAction): void {
  pending.set(itemId, action);
}

export function takePendingNoteAction(itemId: string): PendingNoteAction | undefined {
  const action = pending.get(itemId);
  pending.delete(itemId);
  return action;
}

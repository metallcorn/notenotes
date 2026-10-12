// Найти текст в открытой заметке и прокрутить к нему.
//
// Жалоба владельца 12.10: «не могу кликнуть на ссылку заметки и перейти к
// тому месту, где эта дата». Кнопка «Открыть» в напоминании о сроке
// открывала заметку целиком — а это 12 554 символа распознанного текста
// сервисной книжки, и дату в ней надо искать глазами.
//
// ПОЧЕМУ ИЩЕМ ПО ТЕКСТУ, А НЕ ПО ЯКОРЮ. Якорь (как у reminderAnchor)
// требует, чтобы в документе заранее стоял узел с id. Здесь документ —
// распознанный OCR текст, в него никто ничего не вставлял, и вставлять
// не надо: сроки находит код, а не человек. Поиск по строке работает на
// любом тексте и ничего в заметке не меняет.
//
// ЧЕМ ИСКАТЬ. Датой в формате «10.12.2026» — она короткая, переживает
// рендер (в отличие от markdown-разметки и HTML-сущностей исходника) и
// совпадает с тем, как её пишут в польских и русских документах. Если не
// нашлось — просто ничего не делаем: заметка открыта, и это уже лучше,
// чем ошибка.

type MinimalEditor = {
  state: { doc: { descendants: (fn: (node: DocNode, pos: number) => void) => void } };
  view: { domAtPos: (pos: number) => { node: Node } };
};

type DocNode = { isText?: boolean; text?: string | null };

/** Позиция первого вхождения или null. */
export function findTextPosition(editor: MinimalEditor, needle: string): number | null {
  if (!needle.trim()) return null;
  let found: number | null = null;
  editor.state.doc.descendants((node, pos) => {
    if (found !== null || !node.isText || !node.text) return;
    const index = node.text.indexOf(needle);
    if (index >= 0) found = pos + index;
  });
  return found;
}

/**
 * Прокрутить к найденному и подсветить на пару секунд.
 *
 * Фокус в редактор НЕ переводим намеренно: на телефоне это открыло бы
 * клавиатуру поверх того самого места, к которому мы только что
 * прокрутили.
 */
export function scrollToText(editor: MinimalEditor, needle: string): boolean {
  const position = findTextPosition(editor, needle);
  if (position === null) return false;

  const { node } = editor.view.domAtPos(position);
  const element = (node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as HTMLElement)) ?? null;
  if (!element) return false;

  element.scrollIntoView({ behavior: "smooth", block: "center" });
  // Тот же класс, что у подсветки якоря напоминания — один вид подсветки
  // на оба случая, человеку не надо учить два.
  element.classList.add("reminder-anchor-highlight");
  setTimeout(() => element.classList.remove("reminder-anchor-highlight"), 2500);
  return true;
}

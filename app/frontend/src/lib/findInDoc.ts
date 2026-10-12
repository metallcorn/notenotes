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
  view: { domAtPos: (pos: number) => { node: Node }; dom?: HTMLElement };
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
 * Элемент вложения по id загрузки.
 *
 * ЗАЧЕМ ВТОРАЯ СТРАТЕГИЯ. Срок документа находится не только в тексте
 * заметки, но и в РАСПОЗНАННОМ ТЕКСТЕ ФАЙЛА — он хранится на загрузке, а
 * не внутри заметки. Живой случай 12.10: «Техосмотр Citroën», дата
 * 11.03.2027 есть в transcript фотографии 1000016704.jpg и отсутствует в
 * content заметки, так что поиск по строке не нашёл бы ничего.
 *
 * В таком случае прокручивать надо к самому вложению: человек хотел
 * попасть к документу, а документ — это картинка или PDF в заметке.
 */
function findAttachmentElement(editor: MinimalEditor, uploadId: string): HTMLElement | null {
  const root = (editor as { view: { dom?: HTMLElement } }).view.dom;
  if (!root || !uploadId) return null;
  // src — у картинок и видео, data-url — у блока документа
  // (serialize_document_attachment).
  return root.querySelector<HTMLElement>(`[src*="${uploadId}"], [data-url*="${uploadId}"]`);
}

/**
 * Прокрутить к найденному и подсветить на пару секунд.
 *
 * Фокус в редактор НЕ переводим намеренно: на телефоне это открыло бы
 * клавиатуру поверх того самого места, к которому мы только что
 * прокрутили.
 */
export function scrollToText(editor: MinimalEditor, needle: string): boolean {
  // Сначала текст, потом вложение. Одно поле `find` на две стратегии —
  // чтобы не плодить второй параметр через всю цепочку (бэкенд → payload
  // → ссылка → URL → AppShell → ItemView → редактор). Строка-дата и
  // UUID загрузки не пересекаются, спутать их нельзя.
  const position = findTextPosition(editor, needle);
  const element = position === null
    ? findAttachmentElement(editor, needle)
    : (() => {
        const { node } = editor.view.domAtPos(position);
        return (node.nodeType === Node.TEXT_NODE ? node.parentElement : (node as HTMLElement)) ?? null;
      })();
  if (!element) return false;

  element.scrollIntoView({ behavior: "smooth", block: "center" });
  // Тот же класс, что у подсветки якоря напоминания — один вид подсветки
  // на оба случая, человеку не надо учить два.
  element.classList.add("reminder-anchor-highlight");
  setTimeout(() => element.classList.remove("reminder-anchor-highlight"), 2500);
  return true;
}

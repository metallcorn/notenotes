import type { Editor } from "@tiptap/core";
import { NodeSelection, Selection } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";

// Реальная жалоба (28.10, «мне это уже чинили»): «ставлю курсор в конец
// строки — не печатает; надо кликнуть выше, что-то напечатать, и только
// потом конец строки оживает». Воспроизведено e2e (end-of-line.spec.ts).
//
// Механика. Заметка начинается с горизонтальной линии (или картинки —
// любого выделяемого атом-узла). При загрузке документа ProseMirror
// выбирает Selection.atStart, а для документа, начинающегося с такого
// узла, это НЕ текстовый курсор, а невидимое выделение самого узла
// (NodeSelection, visible=false). Chrome при таком выделении на клик
// рядом с жёстким переносом (`<br>`, конец строки) вообще не двигает
// DOM-курсор — ProseMirror не получает selectionchange и ничего не
// делает. Сам ProseMirror об этой причуде знает (комментарий в
// LeftMouseDown.up: «Chrome will sometimes treat a node selection as a
// cursor…»), но обходит её только когда клик в двух позициях от
// выделенного узла. Набранный текст в итоге ЗАМЕНЯЕТ выделенную линию
// в самом верху заметки — пользователь видит, что «ничего не выводится»,
// и теряет первую линию. Клик в середину текста Chrome отрабатывает, и
// после него выделение становится текстовым — отсюда «надо сначала
// где-то выше что-то напечатать».
//
// Два рубежа, оба здесь:
//  - settleOnText — после загрузки содержимого не оставлять редактор в
//    невидимом выделении узла: встать текстовым курсором на первое
//    место, где можно печатать;
//  - clickIntoText — если выделение всё же невидимое (пользователь сам
//    кликнул по картинке/линии, а потом в текст), на клике по тексту
//    ставить курсор самим, не полагаясь на браузер.

function firstTextSelection(doc: Selection["$from"]["doc"]): Selection | null {
  return Selection.findFrom(doc.resolve(0), 1, true);
}

export function settleOnText(editor: Editor): void {
  const { state, view } = editor;
  if (state.selection.visible) return;
  const selection = firstTextSelection(state.doc);
  if (!selection) return;
  view.dispatch(state.tr.setSelection(selection));
}

// editorProps.handleClick: true — клик обработан, ProseMirror дальше не
// идёт. На клик по выделяемому атом-узлу (картинка, линия) не реагируем:
// там ProseMirror сам выделит узел, это штатное поведение.
export function clickIntoText(view: EditorView, pos: number, event: MouseEvent): boolean {
  if (view.state.selection.visible || event.button !== 0 || event.shiftKey) return false;
  const coords = view.posAtCoords({ left: event.clientX, top: event.clientY });
  if (coords && coords.inside > -1) {
    const node = view.state.doc.nodeAt(coords.inside);
    if (node && node.isAtom && NodeSelection.isSelectable(node)) return false;
  }
  const selection = Selection.near(view.state.doc.resolve(pos));
  if (!selection.visible) return false;
  view.dispatch(view.state.tr.setSelection(selection));
  view.focus();
  return true;
}

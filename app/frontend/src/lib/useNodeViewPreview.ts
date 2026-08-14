import { useEffect, useState } from "react";
import type { Editor } from "@tiptap/react";

// Реальная просьба: если файл/ссылка стоит ОДНА посреди обычного текста
// заметки — превью должно быть компактным (не разбивать чтение большой
// карточкой), раскрывается по ховеру/тапу. А если пользователь накидал
// пачку ссылок или файлов ПОДРЯД, один на строку (типичный кейс —
// собранная подборка) — там как раз ХОЧЕТСЯ сразу видеть богатые карточки
// без лишнего действия на каждую. Различаем не "одна ли нода в параграфе"
// (documentAttachment/linkPreview — блочные атом-узлы, они и так всегда
// одни в своём "параграфе" по определению схемы) — а есть ли РЯДОМ (сосед
// сверху или снизу) ещё один узел того же типа: это и есть сигнал "здесь
// подборка", а не "одна ссылка среди текста".
const STACKABLE_TYPES = new Set(["documentAttachment", "linkPreview"]);

export function useIsPartOfAttachmentStack(editor: Editor | null, getPos: (() => number) | boolean): boolean {
  const [stacked, setStacked] = useState(false);

  useEffect(() => {
    if (!editor || typeof getPos !== "function") return;

    function update() {
      const pos = getPos as () => number;
      let $pos;
      try {
        $pos = editor!.state.doc.resolve(pos());
      } catch {
        return;
      }
      const parent = $pos.parent;
      const index = $pos.index();
      const prev = index > 0 ? parent.child(index - 1) : null;
      const next = index < parent.childCount - 1 ? parent.child(index + 1) : null;
      setStacked(
        (prev !== null && STACKABLE_TYPES.has(prev.type.name)) ||
          (next !== null && STACKABLE_TYPES.has(next.type.name)),
      );
    }

    update();
    editor.on("update", update);
    editor.on("selectionUpdate", update);
    return () => {
      editor.off("update", update);
      editor.off("selectionUpdate", update);
    };
  }, [editor, getPos]);

  return stacked;
}

// Тач-устройства не умеют hover — первый тап открывает превью вместо
// мгновенного перехода/открытия, второй тап (когда превью уже показано)
// подтверждает действие. На мыши (hover доступен) ведём себя как раньше —
// ничего не перехватываем, обычный клик.
export function useTapReveal() {
  const [revealed, setRevealed] = useState(false);

  function handleTap(e: { preventDefault: () => void }, onConfirm: () => void) {
    const isCoarsePointer = window.matchMedia("(hover: none)").matches;
    if (!isCoarsePointer) {
      onConfirm();
      return;
    }
    if (!revealed) {
      e.preventDefault();
      setRevealed(true);
      return;
    }
    onConfirm();
  }

  return { revealed, setRevealed, handleTap };
}

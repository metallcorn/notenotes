import type { Editor } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { useEffect, useState } from "react";

// Соседи блочного узла в документе — чтобы картинка и карточка
// распознанного текста под ней рисовались одним целым (запрос 23.10):
// карточка берёт ширину и выравнивание у картинки перед собой, картинка
// без скругления снизу, если за ней карточка. Хранение не меняется —
// это по-прежнему два узла подряд.
export function nodeAfter(editor: Editor, getPos: unknown, node: PMNode): PMNode | null {
  try {
    if (typeof getPos !== "function") return null;
    const pos = (getPos as () => number)();
    return editor.state.doc.resolve(pos + node.nodeSize).nodeAfter ?? null;
  } catch {
    return null;
  }
}

export function nodeBefore(editor: Editor, getPos: unknown): PMNode | null {
  try {
    if (typeof getPos !== "function") return null;
    const pos = (getPos as () => number)();
    return editor.state.doc.resolve(pos).nodeBefore ?? null;
  } catch {
    return null;
  }
}

// NodeView перерисовывается только при изменении СВОЕГО узла; изменение
// соседа (ширина картинки) надо дослушать отдельно.
export function useEditorTick(editor: Editor): number {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!editor || typeof editor.on !== "function") return;
    const bump = () => setTick((n) => n + 1);
    editor.on("update", bump);
    return () => {
      editor.off("update", bump);
    };
  }, [editor]);
  return tick;
}

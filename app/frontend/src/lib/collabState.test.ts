import { Editor, Node } from "@tiptap/core";
import { EditorState } from "@tiptap/pm/state";
import * as Y from "yjs";
import { Awareness } from "y-protocols/awareness";
import { describe, expect, it } from "vitest";
import StarterKit from "@tiptap/starter-kit";
import { TrailingParagraph } from "../extensions/TrailingParagraph";
import { attachCollab } from "./collabState";
import type { CollabProvider } from "./collabProvider";

// Минимальный атом-узел вместо реального DeliveryAttachment/UrlCheckAttachment
// (те тянут React NodeView с react-query — лишнее для этого теста, баг не в
// конкретном виджете, а в общем механизме appendTransaction при collab-attach).
const TestWidget = Node.create({
  name: "widget",
  group: "block",
  atom: true,
  parseHTML: () => [{ tag: "div[data-widget]" }],
  renderHTML: () => ["div", { "data-widget": "" }],
});

function makeFakeProvider(seedDoc: Y.Doc): CollabProvider {
  return {
    doc: seedDoc,
    awareness: new Awareness(seedDoc),
    // Синхронный "сеятель" — сразу вызывает коллбэк, как самая первая
    // сессия свежей комнаты в app/collab.py, без реального WebSocket.
    connect: (onSeedRequested: () => void) => {
      onSeedRequested();
      return Promise.resolve();
    },
    markSeedComplete: () => {},
    disconnect: () => {},
  } as unknown as CollabProvider;
}

describe("attachCollab — appendTransaction после сидирования комнаты", () => {
  it(
    "заметка, заканчивающаяся атом-узлом, получает параграф после себя сразу, " +
      "не только после следующей правки в другом месте документа",
    async () => {
      const extensions = [StarterKit, TrailingParagraph, TestWidget];
      const editor = new Editor({ extensions, content: "<p></p>" });

      const provider = makeFakeProvider(new Y.Doc());
      await attachCollab(editor, extensions, provider, '<div data-widget=""></div>', {
        name: "Тест",
        color: "#000",
      });

      // Реальный найденный баг: attachCollab применял начальное состояние
      // через updateState (в обход dispatch), поэтому TrailingParagraph
      // (appendTransaction-плагин) не успевал сработать — курсор после
      // виджета некуда было поставить, пока пользователь не печатал что-то
      // ещё в другом месте документа (любая обычная правка — уже dispatch).
      expect(editor.state.doc.lastChild?.type.name).toBe("paragraph");

      editor.destroy();
    },
  );

  it("EditorState.create сам по себе НЕ прогоняет appendTransaction (почему updateState не чинит) — dispatch чинит", () => {
    const extensions = [StarterKit, TrailingParagraph, TestWidget];
    const editor = new Editor({ extensions, content: "<p></p>" });
    const widgetNode = editor.schema.nodes.widget.create();
    const docEndingInWidget = editor.schema.topNodeType.create(null, [
      editor.schema.nodes.paragraph.create(),
      widgetNode,
    ]);

    const createdState = EditorState.create({
      schema: editor.schema,
      doc: docEndingInWidget,
      plugins: editor.state.plugins,
    });
    expect(createdState.doc.lastChild?.type.name).toBe("widget");

    const dispatchedState = createdState.apply(createdState.tr);
    expect(dispatchedState.doc.lastChild?.type.name).toBe("paragraph");

    editor.destroy();
  });
});

import { Editor } from "@tiptap/core";
import { NodeSelection, TextSelection } from "@tiptap/pm/state";
import type { EditorView } from "@tiptap/pm/view";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { describe, expect, it } from "vitest";
import { clickIntoText, settleOnText } from "./editorSelection";

function makeEditor(content: string) {
  return new Editor({ extensions: [StarterKit, Markdown], content });
}

// Подменяем только то, что в jsdom не работает (posAtCoords — нужна
// раскладка), остальное — настоящий редактор.
function fakeView(editor: Editor, inside: number): EditorView {
  return {
    get state() {
      return editor.state;
    },
    posAtCoords: () => ({ pos: 0, inside }),
    dispatch: (tr: Parameters<EditorView["dispatch"]>[0]) => editor.view.dispatch(tr),
    focus: () => undefined,
  } as unknown as EditorView;
}

describe("settleOnText", () => {
  it("документ с линии: невидимое выделение узла → текстовый курсор в первом абзаце", () => {
    const editor = makeEditor("---\n\nПервая строка");
    expect(editor.state.selection).toBeInstanceOf(NodeSelection);
    settleOnText(editor);
    expect(editor.state.selection).toBeInstanceOf(TextSelection);
    expect(editor.state.selection.$from.parent.type.name).toBe("paragraph");
  });

  it("обычный текст: выделение не трогаем", () => {
    const editor = makeEditor("Первая строка");
    const before = editor.state.selection;
    settleOnText(editor);
    expect(editor.state.selection).toBe(before);
  });

  it("документ из одной линии: печатать некуда, выделение остаётся", () => {
    const editor = makeEditor("---");
    expect(() => settleOnText(editor)).not.toThrow();
    expect(editor.state.selection).toBeInstanceOf(NodeSelection);
  });
});

describe("clickIntoText", () => {
  const click = { button: 0, shiftKey: false, clientX: 0, clientY: 0 } as MouseEvent;

  it("при выделенной линии клик в конец строки ставит текстовый курсор туда", () => {
    const editor = makeEditor("---\n\nabc");
    expect(editor.state.selection).toBeInstanceOf(NodeSelection);
    const endOfText = editor.state.doc.content.size - 1;
    const handled = clickIntoText(fakeView(editor, 1), endOfText, click);
    expect(handled).toBe(true);
    expect(editor.state.selection).toBeInstanceOf(TextSelection);
    expect(editor.state.selection.from).toBe(endOfText);
  });

  it("при текстовом курсоре не вмешивается", () => {
    const editor = makeEditor("abc");
    expect(clickIntoText(fakeView(editor, 0), 2, click)).toBe(false);
  });

  it("клик по самой линии оставляет выделение узла ProseMirror'у", () => {
    const editor = makeEditor("---\n\nabc");
    expect(clickIntoText(fakeView(editor, 0), 0, click)).toBe(false);
    expect(editor.state.selection).toBeInstanceOf(NodeSelection);
  });

  it("shift-клик (расширение выделения) не перехватывает", () => {
    const editor = makeEditor("---\n\nabc");
    expect(clickIntoText(fakeView(editor, 1), 3, { ...click, shiftKey: true } as MouseEvent)).toBe(false);
  });
});

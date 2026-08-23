import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { describe, expect, it } from "vitest";
import { NoteLink } from "./NoteLink";

function makeEditor(content?: string) {
  return new Editor({ extensions: [StarterKit, Markdown, NoteLink], content });
}

describe("NoteLink — markdown round-trip", () => {
  it("сериализует ссылку с itemId и названием", () => {
    const editor = makeEditor();
    editor.commands.insertContent({ type: "noteLink", attrs: { itemId: "abc-123", title: "Рецепт борща" } });

    const md = editor.storage.markdown.getMarkdown();
    expect(md).toContain('data-item-id="abc-123"');
    expect(md).toContain("Рецепт борща");

    editor.destroy();
  });

  it("парсит markdown-ссылку обратно с теми же itemId/title", () => {
    const markdown = '<a data-note-link data-item-id="xyz-789" data-title="Список покупок">Список покупок</a>';
    const editor = makeEditor(markdown);

    let found: { itemId?: string; title?: string } = {};
    editor.state.doc.descendants((node) => {
      if (node.type.name === "noteLink") found = { itemId: node.attrs.itemId, title: node.attrs.title };
    });

    expect(found.itemId).toBe("xyz-789");
    expect(found.title).toBe("Список покупок");
    editor.destroy();
  });

  it("полный round-trip внутри обычного текста абзаца", () => {
    const editor1 = makeEditor();
    editor1.commands.insertContent([
      { type: "paragraph", content: [{ type: "text", text: "Смотри " }, { type: "noteLink", attrs: { itemId: "id-1", title: "Другая заметка" } }, { type: "text", text: " для деталей." }] },
    ]);
    const md = editor1.storage.markdown.getMarkdown();
    editor1.destroy();

    const editor2 = makeEditor(md);
    let itemId = "";
    let title = "";
    let paragraphText = "";
    editor2.state.doc.descendants((node) => {
      if (node.type.name === "noteLink") {
        itemId = node.attrs.itemId;
        title = node.attrs.title;
      }
      // noteLink — атом без ProseMirror-содержимого: его подпись видна в
      // renderHTML/DOM, но не входит в textContent (та собирает только
      // настоящие текстовые узлы модели) — заголовок проверяем отдельно.
      if (node.type.name === "paragraph") paragraphText = node.textContent;
    });

    expect(itemId).toBe("id-1");
    expect(title).toBe("Другая заметка");
    expect(paragraphText).toContain("Смотри");
    expect(paragraphText).toContain("для деталей");
    editor2.destroy();
  });
});

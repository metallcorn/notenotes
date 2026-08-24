import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { describe, expect, it } from "vitest";
import { ResizableImage } from "./ResizableImage";

function makeEditor(content?: string) {
  return new Editor({ extensions: [StarterKit, Markdown, ResizableImage], content });
}

// Реальный запрос: телефон снял горизонтально, в заметке читать
// невозможно — поворот должен СОХРАНЯТЬСЯ (не сбрасываться при
// перезагрузке заметки), значит обязан пережить markdown round-trip.
describe("ResizableImage — rotation переживает markdown round-trip", () => {
  it("без поворота (rotation=0) сериализуется как обычный ![]()", () => {
    const editor = makeEditor();
    editor.commands.insertContent({ type: "image", attrs: { src: "/api/uploads/x", alt: "фото" } });
    const md = editor.storage.markdown.getMarkdown();
    expect(md).toBe("![фото](/api/uploads/x)");
    expect(md).not.toContain("data-rotate");
    editor.destroy();
  });

  it("с поворотом сериализуется как <img> с data-rotate", () => {
    const editor = makeEditor();
    editor.commands.insertContent({ type: "image", attrs: { src: "/api/uploads/x", rotation: 90 } });
    const md = editor.storage.markdown.getMarkdown();
    expect(md).toContain('data-rotate="90"');
    editor.destroy();
  });

  it("полный round-trip: сериализовать -> распарсить обратно даёт тот же rotation", () => {
    const editor1 = makeEditor();
    editor1.commands.insertContent({ type: "image", attrs: { src: "/api/uploads/x", rotation: 270 } });
    const md = editor1.storage.markdown.getMarkdown();
    editor1.destroy();

    const editor2 = makeEditor(md);
    let rotation: number | undefined;
    editor2.state.doc.descendants((node) => {
      if (node.type.name === "image") rotation = node.attrs.rotation;
    });
    expect(rotation).toBe(270);
    editor2.destroy();
  });

  it("rotation вместе с width/align в одном теге", () => {
    const editor1 = makeEditor();
    editor1.commands.insertContent({
      type: "image",
      attrs: { src: "/api/uploads/x", width: "50%", align: "center", rotation: 180 },
    });
    const md = editor1.storage.markdown.getMarkdown();
    editor1.destroy();

    const editor2 = makeEditor(md);
    let attrs: { width?: string; align?: string; rotation?: number } = {};
    editor2.state.doc.descendants((node) => {
      if (node.type.name === "image") attrs = node.attrs;
    });
    expect(attrs.width).toBe("50%");
    expect(attrs.align).toBe("center");
    expect(attrs.rotation).toBe(180);
    editor2.destroy();
  });
});

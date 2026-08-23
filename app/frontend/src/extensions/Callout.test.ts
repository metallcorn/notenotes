import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { describe, expect, it } from "vitest";
import { Callout } from "./Callout";

// Реальный риск: сериализация callout в markdown построена на ручном
// использовании MarkdownSerializerState (write/closeBlock/renderContent) —
// без реального round-trip теста легко ошибиться в пустых строках вокруг
// вложенного контента (GFM отличает HTML-блок от markdown внутри именно по
// ним). Проверяем и сериализацию, и обратный парсинг.
function makeEditor(content?: string) {
  return new Editor({ extensions: [StarterKit, Markdown, Callout], content });
}

describe("Callout — markdown round-trip", () => {
  it("сериализует спойлер с заголовком и вложенным параграфом", () => {
    const editor = makeEditor();
    editor.commands.insertContent({
      type: "callout",
      attrs: { variant: "spoiler", title: "Детали", open: true },
      content: [{ type: "paragraph", content: [{ type: "text", text: "Скрытый текст" }] }],
    });

    const md = editor.storage.markdown.getMarkdown();
    expect(md).toContain('data-callout="spoiler"');
    expect(md).toContain('data-title="Детали"');
    expect(md).toContain("Скрытый текст");
    // Пустая строка между открывающим тегом и содержимым — обязательна
    // для GFM/markdown-it, иначе всё уйдёт внутрь одного html_block и
    // **markdown** внутри не распознается.
    expect(md).toMatch(/data-callout="spoiler"[^>]*>\n\n/);

    editor.destroy();
  });

  it("закрытый (open:false) спойлер сериализует data-open=\"0\"", () => {
    const editor = makeEditor();
    editor.commands.insertContent({
      type: "callout",
      attrs: { variant: "spoiler", title: "Т", open: false },
      content: [{ type: "paragraph", content: [{ type: "text", text: "x" }] }],
    });
    expect(editor.storage.markdown.getMarkdown()).toContain('data-open="0"');
    editor.destroy();
  });

  it("парсит markdown callout обратно в узел с правильными атрибутами и содержимым", () => {
    const markdown = [
      '<div data-callout="warning">',
      "",
      "Осторожно, **важный** текст.",
      "",
      "</div>",
    ].join("\n");

    const editor = makeEditor(markdown);
    const found: { variant?: string; text?: string } = {};
    editor.state.doc.descendants((node) => {
      if (node.type.name === "callout") {
        found.variant = node.attrs.variant;
        found.text = node.textContent;
      }
    });

    expect(found.variant).toBe("warning");
    expect(found.text).toContain("Осторожно");
    expect(found.text).toContain("важный");
    editor.destroy();
  });

  it("полный round-trip: сериализовать → распарсить обратно даёт тот же вариант/заголовок/текст", () => {
    const editor1 = makeEditor();
    editor1.commands.insertContent({
      type: "callout",
      attrs: { variant: "danger", title: null, open: true },
      content: [
        { type: "paragraph", content: [{ type: "text", text: "Первый абзац" }] },
        { type: "paragraph", content: [{ type: "text", text: "Второй абзац" }] },
      ],
    });
    const md = editor1.storage.markdown.getMarkdown();
    editor1.destroy();

    const editor2 = makeEditor(md);
    let variant = "";
    const paragraphs: string[] = [];
    editor2.state.doc.descendants((node) => {
      if (node.type.name === "callout") variant = node.attrs.variant;
      if (node.type.name === "paragraph" && node.textContent) paragraphs.push(node.textContent);
    });

    expect(variant).toBe("danger");
    expect(paragraphs).toEqual(["Первый абзац", "Второй абзац"]);
    editor2.destroy();
  });

  it("две плашки подряд не сливаются в одну (пустая строка после закрывающего тега)", () => {
    const editor = makeEditor();
    editor.commands.insertContent([
      { type: "callout", attrs: { variant: "hint" }, content: [{ type: "paragraph", content: [{ type: "text", text: "A" }] }] },
      { type: "callout", attrs: { variant: "info" }, content: [{ type: "paragraph", content: [{ type: "text", text: "B" }] }] },
    ]);
    const md = editor.storage.markdown.getMarkdown();
    editor.destroy();

    const editor2 = makeEditor(md);
    const variants: string[] = [];
    editor2.state.doc.descendants((node) => {
      if (node.type.name === "callout") variants.push(node.attrs.variant);
    });
    expect(variants).toEqual(["hint", "info"]);
    editor2.destroy();
  });
});

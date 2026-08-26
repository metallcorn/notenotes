import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { describe, expect, it } from "vitest";
import { UrlCheckAttachment, serializeUrlCheck } from "./UrlCheckAttachment";

function makeEditor(content?: string) {
  return new Editor({ extensions: [StarterKit, Markdown, UrlCheckAttachment], content });
}

// Реальный найденный баг: плашка «Проверить по ссылке» переставала
// находить виджет после сохранения — причина оказалась в том, что
// сериализация в markdown слепо подставляла attrs.id в шаблонную строку,
// а JS сериализует null в ЛИТЕРАЛЬНУЮ строку "null", неотличимую на вид от
// настоящего id — при автосохранении это навсегда запекалось в content.
describe("serializeUrlCheck — не запекает null как строку", () => {
  it("с настоящим id пишет data-url-check-id как раньше", () => {
    expect(serializeUrlCheck("85d353e9-2ab6-41e8-b575-7cafdd0ed167")).toBe(
      '<div data-url-check data-url-check-id="85d353e9-2ab6-41e8-b575-7cafdd0ed167"></div>',
    );
  });

  it("с null НЕ пишет data-url-check-id вообще (не строку 'null')", () => {
    const tag = serializeUrlCheck(null);
    expect(tag).not.toContain("null");
    expect(tag).toBe("<div data-url-check></div>");
  });

  it("с undefined — то же самое", () => {
    expect(serializeUrlCheck(undefined)).toBe("<div data-url-check></div>");
  });
});

describe("UrlCheckAttachment — markdown round-trip", () => {
  it("узел с id переживает round-trip без потерь", () => {
    const editor1 = makeEditor();
    editor1.commands.insertContent({ type: "urlCheck", attrs: { id: "85d353e9-2ab6-41e8-b575-7cafdd0ed167" } });
    const md = editor1.storage.markdown.getMarkdown();
    editor1.destroy();

    expect(md).not.toContain("null");
    const editor2 = makeEditor(md);
    let id: string | null = null;
    editor2.state.doc.descendants((node) => {
      if (node.type.name === "urlCheck") id = node.attrs.id;
    });
    expect(id).toBe("85d353e9-2ab6-41e8-b575-7cafdd0ed167");
    editor2.destroy();
  });

  it("узел с null id сериализуется и парсится обратно как null, не как строка 'null' (регресс)", () => {
    const editor1 = makeEditor();
    editor1.commands.insertContent({ type: "urlCheck", attrs: { id: null } });
    const md = editor1.storage.markdown.getMarkdown();
    editor1.destroy();

    expect(md).not.toContain("null");
    const editor2 = makeEditor(md);
    let id: string | null = "unset";
    editor2.state.doc.descendants((node) => {
      if (node.type.name === "urlCheck") id = node.attrs.id;
    });
    expect(id).toBeNull();
    editor2.destroy();
  });
});

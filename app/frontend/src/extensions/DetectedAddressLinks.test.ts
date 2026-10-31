import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { describe, expect, it } from "vitest";
import { findAddressPositions } from "./DetectedAddressLinks";

function makeEditor(markdown: string) {
  return new Editor({ extensions: [StarterKit, Markdown], content: markdown });
}

describe("DetectedAddressLinks — поиск адреса в документе", () => {
  it("находит адрес внутри одного текстового узла", () => {
    const editor = makeEditor("Встреча: ul. Przykładowa 1, Poznań, в 10:00");
    const found = findAddressPositions(editor.state.doc, [{ text: "ul. Przykładowa 1, Poznań", query: "q" }]);
    expect(found).toHaveLength(1);
    expect(editor.state.doc.textBetween(found[0].pos, found[0].pos + 17)).toBe("ul. Przykładowa 1");
    editor.destroy();
  });

  it("находит жирный адрес, разбитый жёстким переносом, по Markdown-исходнику", () => {
    // Так присылает Telegram: улица жирным, название места с новой строки.
    const editor = makeEditor("Адрес для консультации\\\n**ul. Przykładowa 1**\\\nGabinet Lorem");
    const found = findAddressPositions(editor.state.doc, [
      { text: "**ul. Przykładowa 1 **\nGabinet Lorem", query: "Gabinet Lorem, ul. Przykładowa 1" },
    ]);
    expect(found).toHaveLength(1);
    expect(found[0].query).toBe("Gabinet Lorem, ul. Przykładowa 1");
    expect(editor.state.doc.textBetween(found[0].pos, found[0].pos + 3)).toBe("ul.");
    editor.destroy();
  });

  it("не находит адрес, которого в тексте уже нет, и не ищет по пустой строке", () => {
    const editor = makeEditor("Текст без адреса");
    expect(findAddressPositions(editor.state.doc, [{ text: "ul. Przykładowa 5", query: "q" }])).toEqual([]);
    expect(findAddressPositions(editor.state.doc, [{ text: "", query: "q" }])).toEqual([]);
    editor.destroy();
  });

  it("считает каждое вхождение в разных абзацах", () => {
    const editor = makeEditor("Сюда: ul. Przykładowa 1\n\nИ обратно: ul. Przykładowa 1");
    const found = findAddressPositions(editor.state.doc, [{ text: "ul. Przykładowa 1", query: "q" }]);
    expect(found).toHaveLength(2);
    expect(found[0].pos).toBeLessThan(found[1].pos);
    editor.destroy();
  });
});

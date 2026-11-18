import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { describe, expect, it, vi } from "vitest";

// Карточка тянет хуки данных и роутер — для проверки сериализации узла
// она не нужна, подменяем пустышкой.
vi.mock("../components/ChartEmbedCard", () => ({ default: () => null }));

import { ChartEmbed, serializeChart } from "./ChartEmbed";

function makeEditor(content?: string) {
  return new Editor({ extensions: [StarterKit, Markdown.configure({ html: true }), ChartEmbed], content });
}

const attrs = { tableId: "6f1c2e3a-0000-4000-8000-000000000001", kind: "line" as const, x: "c-date", y: ["c-val", "c-norm"], series: "c-name", size: null, title: 'Кровь "2026" <A&B>' };

describe("ChartEmbed", () => {
  it("тег совпадает с тем, что пишет бэкенд (tools/charts.py)", () => {
    expect(serializeChart({ ...attrs, series: null, y: ["c-val"], title: "" })).toBe(
      '<div data-chart data-table-id="6f1c2e3a-0000-4000-8000-000000000001" data-kind="line" data-x="c-date" data-y="c-val"></div>',
    );
  });

  it("round-trip через markdown сохраняет столбцы, серии и подпись с кавычками", () => {
    const editor1 = makeEditor();
    editor1.commands.insertContent({ type: "chartEmbed", attrs });
    const md = editor1.storage.markdown.getMarkdown();
    editor1.destroy();

    expect(md).toContain('data-y="c-val,c-norm"');
    expect(md).toContain("&quot;2026&quot;");
    expect(md).not.toContain("null");

    const editor2 = makeEditor(md);
    let parsed: Record<string, unknown> | null = null;
    editor2.state.doc.descendants((node) => {
      if (node.type.name === "chartEmbed") parsed = node.attrs;
    });
    expect(parsed).toEqual(attrs);
    editor2.destroy();
  });

  it("неизвестный вид графика из старого тега читается как линия", () => {
    const editor = makeEditor('<div data-chart data-table-id="t" data-kind="radar" data-y="a"></div>');
    let kind = "";
    editor.state.doc.descendants((node) => {
      if (node.type.name === "chartEmbed") kind = node.attrs.kind;
    });
    expect(kind).toBe("line");
    editor.destroy();
  });
});

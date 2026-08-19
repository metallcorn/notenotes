import { describe, expect, it } from "vitest";
import { listProgress, previewText } from "./NoteList";

describe("previewText", () => {
  it("strips HTML tags", () => {
    expect(previewText("<b>Привет</b> мир")).toBe("Привет мир");
  });

  it("strips markdown images entirely", () => {
    expect(previewText("Текст ![alt](/api/uploads/abc) продолжение")).toBe("Текст продолжение");
  });

  it("keeps link text but drops the URL", () => {
    expect(previewText("Смотри [сюда](https://example.com)")).toBe("Смотри сюда");
  });

  it("strips markdown formatting characters", () => {
    expect(previewText("# Заголовок\n\n**жирный** и _курсив_")).toBe("Заголовок жирный и курсив");
  });

  it("collapses whitespace and truncates to 120 chars", () => {
    const long = "a".repeat(200);
    const result = previewText(long);
    expect(result).toHaveLength(120);
  });

  it("returns empty string for empty content", () => {
    expect(previewText("")).toBe("");
  });
});

describe("listProgress", () => {
  it("returns 'Пусто' for empty content", () => {
    expect(listProgress("")).toBe("Пусто");
  });

  it("counts done vs total lines", () => {
    expect(listProgress("[x] Молоко\n[ ] Хлеб\n[x] Сыр")).toBe("2/3 выполнено");
  });

  it("counts zero done when nothing is checked", () => {
    expect(listProgress("[ ] Молоко\n[ ] Хлеб")).toBe("0/2 выполнено");
  });

  it("ignores blank lines", () => {
    expect(listProgress("[x] Молоко\n\n[ ] Хлеб")).toBe("1/2 выполнено");
  });
});

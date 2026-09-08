import { describe, expect, it } from "vitest";
import { shouldFlushPendingSave } from "./pendingSave";

const pending = { id: "note-a", title: "Заголовок", content: "текст" };

describe("shouldFlushPendingSave", () => {
  it("сохраняет правку догруженной заметки", () => {
    expect(shouldFlushPendingSave(pending, "note-a", false)).toBe(true);
  });

  it("НЕ сохраняет, пока заметка не догрузилась", () => {
    // Ровно этот случай обнулил две заметки 2026-09-08: переключение на
    // заметку и уход с неё раньше, чем подключилась коллаборация.
    expect(shouldFlushPendingSave(pending, null, false)).toBe(false);
  });

  it("НЕ сохраняет состояние одной заметки под id другой", () => {
    expect(shouldFlushPendingSave(pending, "note-b", false)).toBe(false);
  });

  it("НЕ сохраняет пустое содержимое недогруженной заметки", () => {
    // Самая дорогая форма: пустой контент, записанный поверх реального.
    const blank = { id: "note-a", title: "Заголовок", content: "" };
    expect(shouldFlushPendingSave(blank, null, false)).toBe(false);
  });

  it("не сохраняет при доступном обновлении приложения", () => {
    expect(shouldFlushPendingSave(pending, "note-a", true)).toBe(false);
  });

  it("нечего сохранять — нечего и делать", () => {
    expect(shouldFlushPendingSave(null, "note-a", false)).toBe(false);
  });
});

import { describe, expect, it } from "vitest";
import { parseInternalNoteLink } from "./NoteEditor";

// Реальный запрос: вставил в заметку ссылку на другую заметку, скопированную
// из адресной строки браузера (?item=<uuid>) — должна распознаться как
// внутренняя, не как обычная внешняя ссылка на превью.
describe("parseInternalNoteLink", () => {
  const origin = window.location.origin;

  it("распознаёт ссылку на заметку своего домена", () => {
    const id = "e2ea7dab-aea7-4a19-ae9c-db49b5826332";
    expect(parseInternalNoteLink(`${origin}/?list=1&item=${id}`)).toBe(id);
  });

  it("работает независимо от порядка query-параметров", () => {
    const id = "e2ea7dab-aea7-4a19-ae9c-db49b5826332";
    expect(parseInternalNoteLink(`${origin}/?item=${id}&list=1`)).toBe(id);
  });

  it("чужой домен — не считается внутренней ссылкой, даже с похожим item=", () => {
    const id = "e2ea7dab-aea7-4a19-ae9c-db49b5826332";
    expect(parseInternalNoteLink(`https://evil.example.com/?item=${id}`)).toBeNull();
  });

  it("свой домен, но без item= — не внутренняя ссылка", () => {
    expect(parseInternalNoteLink(`${origin}/settings`)).toBeNull();
  });

  it("свой домен с невалидным (не UUID) item= — не внутренняя ссылка", () => {
    expect(parseInternalNoteLink(`${origin}/?item=not-a-uuid`)).toBeNull();
  });

  it("не URL вообще — не бросает, возвращает null", () => {
    expect(parseInternalNoteLink("просто текст")).toBeNull();
  });
});

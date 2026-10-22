import { describe, expect, it } from "vitest";
import { collapseUnchanged, diffStats, lineDiff } from "./lineDiff";

describe("lineDiff", () => {
  it("находит заменённую и добавленную строки", () => {
    const before = "Паспорта\nСтолик на субботу\n";
    const after = "Паспорта\nСтолик на пятницу\nБилеты в музей\n";
    const d = lineDiff(before, after);
    expect(d.filter((l) => l.kind === "del").map((l) => l.text)).toEqual(["Столик на субботу"]);
    expect(d.filter((l) => l.kind === "add").map((l) => l.text)).toEqual(["Столик на пятницу", "Билеты в музей"]);
    expect(diffStats(d)).toEqual({ added: 2, removed: 1 });
  });

  it("одинаковые тексты — только same", () => {
    expect(lineDiff("a\nb", "a\nb").every((l) => l.kind === "same")).toBe(true);
  });

  it("схлопывает длинные неизменённые куски, оставляя контекст", () => {
    const same = Array.from({ length: 10 }, (_, i) => `строка ${i}`).join("\n");
    const d = lineDiff(same + "\nстарое", same + "\nновое");
    const c = collapseUnchanged(d, 2);
    const skip = c.find((x) => x.kind === "skip");
    expect(skip && skip.kind === "skip" ? skip.count : 0).toBe(8);
    // Контекст перед изменением — две последние строки неизменённого куска.
    expect(c.filter((x) => x.kind === "same")).toHaveLength(2);
  });
});

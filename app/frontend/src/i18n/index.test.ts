import { describe, expect, it } from "vitest";
import { en } from "./en";
import { t, tn } from "./index";
import { ru } from "./ru";

describe("i18n", () => {
  it("по умолчанию русский", () => {
    expect(t("nav.trash")).toBe("Корзина");
  });

  it("в английском словаре те же ключи и ни одной пустой строки", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort());
    expect(Object.values(en).every((v) => v.trim() !== "")).toBe(true);
  });

  it("tn подбирает русскую форму слова по числу", () => {
    expect(tn("count.notes", 1)).toBe("1 заметка");
    expect(tn("count.notes", 3)).toBe("3 заметки");
    expect(tn("count.notes", 11)).toBe("11 заметок");
    expect(tn("count.notes", 22)).toBe("22 заметки");
    expect(tn("count.folders", 0)).toBe("0 папок");
  });
});

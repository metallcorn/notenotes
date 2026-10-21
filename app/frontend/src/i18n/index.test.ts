import { describe, expect, it } from "vitest";
import { en } from "./en";
import { t } from "./index";
import { ru } from "./ru";

describe("i18n", () => {
  it("по умолчанию русский", () => {
    expect(t("nav.trash")).toBe("Корзина");
  });

  it("в английском словаре те же ключи и ни одной пустой строки", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(ru).sort());
    expect(Object.values(en).every((v) => v.trim() !== "")).toBe(true);
  });
});

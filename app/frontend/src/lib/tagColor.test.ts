import { describe, expect, it } from "vitest";
import { tagColor } from "./tagColor";

describe("tagColor", () => {
  it("один тег — один цвет, независимо от регистра", () => {
    expect(tagColor("Документы")).toEqual(tagColor("документы"));
    expect(tagColor("банки").chip).toBe(tagColor("банки").chip);
  });

  it("разные теги разводятся по палитре", () => {
    const names = ["документы", "банки", "автомобили", "Германия", "работа", "водительские права", "JDG", "поездка"];
    const distinct = new Set(names.map((n) => tagColor(n).chip));
    expect(distinct.size).toBeGreaterThan(3);
  });

  it("классы содержат светлую и тёмную подложку", () => {
    const c = tagColor("x");
    expect(c.chip).toMatch(/bg-\[#/);
    expect(c.chip).toMatch(/dark:bg-\[#/);
    expect(c.dot).toMatch(/^bg-\[#/);
  });
});

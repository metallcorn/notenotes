import { describe, expect, it } from "vitest";
import { formatBytes } from "./format";

describe("formatBytes", () => {
  it("байты — без дробной части", () => {
    expect(formatBytes(500)).toBe("500 Б");
  });

  it("килобайты", () => {
    expect(formatBytes(2048)).toBe("2 КБ");
  });

  it("мегабайты меньше 10 — один знак после запятой", () => {
    expect(formatBytes(3.5 * 1024 * 1024)).toBe("3.5 МБ");
  });

  it("мегабайты 10 и больше — без дробной части", () => {
    expect(formatBytes(24.7 * 1024 * 1024)).toBe("25 МБ");
  });

  it("гигабайты", () => {
    expect(formatBytes(1.2 * 1024 * 1024 * 1024)).toBe("1.2 ГБ");
  });

  it("0 и отрицательные — 0 Б", () => {
    expect(formatBytes(0)).toBe("0 Б");
    expect(formatBytes(-5)).toBe("0 Б");
  });
});

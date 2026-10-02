import { describe, expect, it } from "vitest";
import { REPEAT_LABELS, REPEAT_RULES, repeatLabel } from "./recurrence";

describe("подписи повтора", () => {
  it("у каждого правила есть русское название", () => {
    for (const rule of REPEAT_RULES) expect(REPEAT_LABELS[rule]).toBeTruthy();
  });

  it("одноразовое — без подписи", () => {
    expect(repeatLabel(null)).toBeNull();
    expect(repeatLabel(undefined)).toBeNull();
    expect(repeatLabel("")).toBeNull();
  });

  it("незнакомое правило показываем как есть, а не ломаем вид", () => {
    // Бэкенд может уйти вперёд (появится пятый период) раньше фронтенда.
    expect(repeatLabel("quarterly")).toBe("quarterly");
  });
});

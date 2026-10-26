import { describe, expect, it } from "vitest";
import type { RoutineDose } from "../api/types";
import { dayOfCourse, deferredNames, humanMinutes, lateMinutes, waitingMinutes } from "./routineFormat";

const dose = (overrides: Partial<RoutineDose> = {}): RoutineDose => ({
  id: "d1",
  planned_at: "2026-10-26T18:00:00Z",
  status: "pending",
  done_at: null,
  done_by: null,
  done_by_name: null,
  deferred_by: [],
  snoozed_until: null,
  nag_until: null,
  late: false,
  ...overrides,
});

describe("routineFormat", () => {
  it("humanMinutes: минуты, часы, часы с минутами", () => {
    expect(humanMinutes(35)).toBe("35 мин");
    expect(humanMinutes(60)).toBe("1 ч");
    expect(humanMinutes(125)).toBe("2 ч 05 мин");
    expect(humanMinutes(125, "en-GB")).toBe("2 h 05 min");
  });

  it("waitingMinutes: ноль до срока, минуты после", () => {
    expect(waitingMinutes(dose(), new Date("2026-10-26T17:50:00Z"))).toBe(0);
    expect(waitingMinutes(dose(), new Date("2026-10-26T18:35:00Z"))).toBe(35);
  });

  it("lateMinutes: до 15 минут — вовремя", () => {
    expect(lateMinutes(dose({ done_at: "2026-10-26T18:10:00Z" }))).toBe(0);
    expect(lateMinutes(dose({ done_at: "2026-10-26T18:40:00Z" }))).toBe(40);
    expect(lateMinutes(dose())).toBe(0);
  });

  it("dayOfCourse: считает день курса и обрезает по границам", () => {
    const course = { starts_on: "2026-10-24", ends_on: "2026-11-06" };
    expect(dayOfCourse(course, new Date(2026, 9, 26, 12))).toEqual({ day: 3, total: 14 });
    expect(dayOfCourse(course, new Date(2026, 9, 1))).toEqual({ day: 1, total: 14 });
    expect(dayOfCourse(course, new Date(2026, 11, 1))).toEqual({ day: 14, total: 14 });
    expect(dayOfCourse({ starts_on: "2026-10-24", ends_on: null })).toBeNull();
  });

  it("deferredNames: без самого читателя", () => {
    const d = dose({ deferred_by: [{ id: "me", name: "Я" }, { id: "u2", name: "Anna" }] });
    expect(deferredNames(d, "me")).toEqual(["Anna"]);
  });
});

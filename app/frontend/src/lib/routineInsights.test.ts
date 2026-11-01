import { describe, expect, it } from "vitest";
import type { RoutineDose } from "../api/types";
import { computeInsights, journalText, levelOf, median, offsetLabel, offsetMinutes, percentile, signedMinutes, slotKey } from "./routineInsights";

// Данные вымышленные: кот Burek, Jan и Anna.

function dose(day: number, planned: string, status: RoutineDose["status"], doneAt?: string, extra: Partial<RoutineDose> = {}): RoutineDose {
  const at = (hhmm: string) => new Date(2026, 9, day, Number(hhmm.slice(0, 2)), Number(hhmm.slice(3))).toISOString();
  return {
    id: `${day}-${planned}`,
    planned_at: at(planned),
    status,
    done_at: doneAt ? at(doneAt) : null,
    done_by: null,
    done_by_name: doneAt ? "Jan" : null,
    deferred_by: [],
    snoozed_until: null,
    nag_until: null,
    late: false,
    ...extra,
  };
}

describe("routineInsights", () => {
  it("считает отклонение и уровень", () => {
    expect(offsetMinutes(dose(1, "16:30", "done", "17:10"))).toBe(40);
    expect(offsetMinutes(dose(1, "16:30", "done", "16:20"))).toBe(-10);
    expect(offsetMinutes(dose(1, "16:30", "skipped"))).toBeNull();
    expect([levelOf(0), levelOf(10), levelOf(11), levelOf(60), levelOf(-61)]).toEqual(["ok", "ok", "warn", "warn", "bad"]);
    expect(offsetLabel(5)).toBe("вовремя");
    expect(offsetLabel(40)).toBe("+40 мин");
    expect(offsetLabel(-12, "en-GB")).toBe("−12 min");
    expect(offsetLabel(95)).toBe("+1 ч 35");
    expect([signedMinutes(0), signedMinutes(1), signedMinutes(-5, "en-GB"), signedMinutes(-120)]).toEqual(["0 мин", "+1 мин", "−5 min", "−2 ч"]);
    // Слот — в поясе рутины: 15:30 UTC это 16:30 в Варшаве зимой.
    expect(slotKey("2026-11-01T15:30:00Z", "Europe/Warsaw")).toBe("16:30");
    expect(slotKey("2026-10-20T14:30:00Z", "Europe/Warsaw")).toBe("16:30");
  });

  it("медиана и процентили", () => {
    expect(median([])).toBeNull();
    expect(median([5, 1, 40])).toBe(5);
    expect(median([1, 40])).toBe(21);
    expect(percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9)).toBe(9);
  });

  it("группирует по слотам и дням, пропуски красит красным", () => {
    const now = new Date(2026, 9, 31, 12, 0);
    const doses = [
      dose(27, "16:30", "done", "16:31"),
      dose(28, "16:30", "done", "17:10"),
      dose(29, "16:30", "done", "18:00"),
      dose(30, "16:30", "skipped"),
      dose(30, "22:00", "missed", undefined, { reported_by_name: "Anna" }),
      dose(31, "16:30", "pending"),
    ];
    const insights = computeInsights(doses, now);
    expect(insights.total).toBe(5);
    expect(insights.done).toBe(3);
    expect(insights.missed).toBe(1);
    expect(insights.skipped).toBe(1);
    expect(insights.offsets).toEqual([1, 40, 90]);
    expect(insights.median).toBe(40);
    expect(insights.within10).toBe(1);
    expect(insights.within60).toBe(1);
    expect(insights.over60).toBe(1);
    expect(insights.slots.map((s) => s.slot)).toEqual(["16:30"]);
    expect(insights.slots[0].plannedMinutes).toBe(16 * 60 + 30);
    expect(insights.slots[0].window).toEqual([1, 90]);
    expect(insights.days).toHaveLength(28);
    const levels = Object.fromEntries(insights.days.map((d) => [d.date.getDate(), d.level]));
    expect(levels[27]).toBe("ok");
    expect(levels[28]).toBe("warn");
    expect(levels[29]).toBe("bad");
    expect(levels[30]).toBe("bad"); // «не дали» перевешивает «не нужно»
    expect(levels[31]).toBe("pending");
    expect(levels[26]).toBe("none");
  });

  it("журнал текстом — по строке на приём, с отклонением", () => {
    const text = journalText({
      title: "Krople",
      subject: "Burek",
      dose: "1 kropla",
      schedule_text: "в 16:30",
      doses: [dose(27, "16:30", "done", "17:10"), dose(28, "16:30", "skipped"), dose(29, "16:30", "missed", undefined, { reported_by_name: "Anna" }), dose(30, "16:30", "pending")],
    });
    expect(text.split("\n")).toEqual([
      "Krople · Burek · 1 kropla · в 16:30",
      "2026-10-27 16:30 → 17:10 (+40 мин) · Jan",
      "2026-10-28 16:30 → не нужно сегодня",
      "2026-10-29 16:30 → пропустили · Anna",
    ]);
  });
});

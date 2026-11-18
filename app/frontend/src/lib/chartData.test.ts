import { describe, expect, it } from "vitest";
import type { TableDetail } from "../api/types";
import { buildPie, buildSeries, detectXKind, niceTicks, parseDate, parseNumber, type ChartSpec } from "./chartData";

// Показания из медицинских документов переписываются в таблицу как есть:
// даты «01.03.2026», числа «72,5», единицы рядом с числом. График обязан
// это читать, а не требовать от человека «правильный» формат.
function table(rows: Record<string, string>[]): TableDetail {
  return {
    id: "t1",
    space_id: "s1",
    folder_id: null,
    title: "Анализы",
    created_at: "",
    updated_at: "",
    columns: [
      { id: "date", name: "Дата", type: "text" },
      { id: "name", name: "Показатель", type: "text" },
      { id: "value", name: "Значение", type: "number" },
      { id: "norm", name: "Норма", type: "number" },
    ],
    rows: rows.map((cells, i) => ({ id: `r${i}`, cells, created_at: "" })),
  };
}

const spec = (overrides: Partial<ChartSpec>): ChartSpec => ({ tableId: "t1", kind: "line", x: "date", y: ["value"], series: null, size: null, title: "", ...overrides });

describe("разбор ячеек", () => {
  it("число с запятой и единицей измерения", () => {
    expect(parseNumber("72,5 кг")).toBe(72.5);
    expect(parseNumber("< 0.5")).toBe(0.5);
    expect(parseNumber("1 250")).toBe(1250);
    expect(parseNumber("—")).toBeNull();
    expect(parseNumber("")).toBeNull();
  });

  it("даты в польско-русской и ISO записи", () => {
    expect(parseDate("01.03.2026")).toBe(new Date(2026, 2, 1).getTime());
    expect(parseDate("2026-03-01 09:30")).toBe(new Date(2026, 2, 1, 9, 30).getTime());
    expect(parseDate("1/3/26")).toBe(new Date(2026, 2, 1).getTime());
    expect(parseDate("31.02.2026")).toBeNull();
    expect(parseDate("вчера")).toBeNull();
  });

  it("вид оси X — по большинству: одна опечатка не превращает даты в подписи", () => {
    expect(detectXKind(["01.03.2026", "01.06.2026", "01.09.2026", "сентябрь", "01.12.2026"])).toBe("date");
    expect(detectXKind(["1", "2", "3"])).toBe("number");
    expect(detectXKind(["Гемоглобин", "Ферритин"])).toBe("category");
    expect(detectXKind([])).toBe("category");
  });
});

describe("серии", () => {
  const t = table([
    { date: "01.06.2026", name: "Гемоглобин", value: "137" },
    { date: "01.03.2026", name: "Гемоглобин", value: "140" },
    { date: "01.03.2026", name: "Ферритин", value: "55" },
    { date: "01.09.2026", name: "Ферритин", value: "—" },
  ]);

  it("длинная таблица: одна линия на показатель, точки по дате по порядку", () => {
    const data = buildSeries(t, spec({ series: "name" }));
    expect(data.xKind).toBe("date");
    expect(data.series.map((s) => s.name)).toEqual(["Гемоглобин", "Ферритин"]);
    expect(data.series[0].points.map((p) => p.y)).toEqual([140, 137]);
    expect(data.series[1].points).toHaveLength(1);
  });

  it("столбцы всегда по категориям, даже если X — даты", () => {
    const data = buildSeries(t, spec({ kind: "bar" }), { categorical: true });
    expect(data.xKind).toBe("category");
    expect(data.categories).toEqual(["01.06.2026", "01.03.2026", "01.09.2026"]);
    expect(data.series[0].name).toBe("Значение");
  });

  it("несколько столбцов Y без серий — серия на столбец", () => {
    const wide = table([
      { date: "01.03.2026", value: "140", norm: "130" },
      { date: "01.06.2026", value: "137", norm: "130" },
    ]);
    const data = buildSeries(wide, spec({ y: ["value", "norm"] }));
    expect(data.series.map((s) => s.name)).toEqual(["Значение", "Норма"]);
  });

  it("без столбца X — номер строки", () => {
    const data = buildSeries(t, spec({ x: null, kind: "scatter" }));
    expect(data.xKind).toBe("number");
    expect(data.series[0].points.map((p) => p.x)).toEqual([1, 2, 3]);
  });
});

describe("круг и деления", () => {
  it("одинаковые подписи складываются, нули и прочерки выпадают", () => {
    const t = table([
      { name: "Гемоглобин", value: "140" },
      { name: "Гемоглобин", value: "60" },
      { name: "Ферритин", value: "0" },
      { name: "СОЭ", value: "—" },
    ]);
    expect(buildPie(t, spec({ kind: "pie", x: "name" }))).toEqual([{ label: "Гемоглобин", value: 200 }]);
  });

  it("деления круглые", () => {
    expect(niceTicks(0, 97)).toEqual([0, 20, 40, 60, 80]);
    expect(niceTicks(132, 141)).toEqual([132, 134, 136, 138, 140]);
    expect(niceTicks(5, 5)).toEqual([5]);
  });
});

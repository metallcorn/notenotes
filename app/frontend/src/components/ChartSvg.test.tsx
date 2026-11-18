import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TableDetail } from "../api/types";
import type { ChartSpec } from "../lib/chartData";
import ChartSvg from "./ChartSvg";

const table: TableDetail = {
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
  ],
  rows: [
    { id: "r1", cells: { date: "01.03.2026", name: "Гемоглобин", value: "140" }, created_at: "" },
    { id: "r2", cells: { date: "01.06.2026", name: "Гемоглобин", value: "137" }, created_at: "" },
    { id: "r3", cells: { date: "01.03.2026", name: "Ферритин", value: "55" }, created_at: "" },
    { id: "r4", cells: { date: "01.06.2026", name: "Ферритин", value: "61" }, created_at: "" },
  ],
};

const base: ChartSpec = { tableId: "t1", kind: "line", x: "date", y: ["value"], series: "name", size: null, title: "Кровь" };

describe("ChartSvg", () => {
  it("линия: по серии на показатель, легенда и точки с подсказками", () => {
    const { container } = render(<ChartSvg table={table} spec={base} />);
    expect(screen.getAllByTestId("chart-series")).toHaveLength(2);
    expect(container.querySelectorAll("path[stroke]")).toHaveLength(2);
    expect(container.querySelectorAll("circle")).toHaveLength(4);
    expect(screen.getByTestId("chart-legend").textContent).toContain("Ферритин");
    expect(container.querySelector("circle title")?.textContent).toContain("140");
  });

  it("столбцы: группа на дату, столбик на серию", () => {
    const { container } = render(<ChartSvg table={table} spec={{ ...base, kind: "bar" }} />);
    expect(container.querySelectorAll("rect")).toHaveLength(4);
  });

  it("круг: доля на показатель, одинаковые подписи сложены", () => {
    render(<ChartSvg table={table} spec={{ ...base, kind: "pie", x: "name", series: null }} />);
    expect(screen.getAllByTestId("chart-slice")).toHaveLength(2);
    expect(screen.getByTestId("chart-legend").textContent).toContain("%");
  });

  it("точки: размер пузырька из столбца", () => {
    const { container } = render(<ChartSvg table={table} spec={{ ...base, kind: "scatter", size: "value" }} />);
    const radii = [...container.querySelectorAll("circle")].map((c) => Number(c.getAttribute("r")));
    expect(Math.max(...radii)).toBeGreaterThan(Math.min(...radii));
  });

  it("без чисел — честное сообщение, не пустой svg", () => {
    const { container } = render(<ChartSvg table={table} spec={{ ...base, y: ["name"] }} />);
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText(/нет чисел/)).toBeTruthy();
  });
});

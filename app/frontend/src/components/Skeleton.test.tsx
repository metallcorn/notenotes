import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ListSkeleton, Skeleton } from "./Skeleton";

// Жалоба владельца 12.10: «подгрузки списков заметок не скелетные, а
// просто родинокий спинер». Разница не косметическая: спиннер по центру
// пустого экрана не говорит, что грузится и сколько этого будет.
describe("ListSkeleton", () => {
  it("рисует запрошенное число строк", () => {
    const { container } = render(<ListSkeleton rows={4} />);

    // Две полосы на строку: заголовок и подпись, плюс иконка.
    expect(container.querySelectorAll(".skeleton")).toHaveLength(4 * 3);
  });

  it("читалке сообщает, что идёт загрузка", () => {
    render(<ListSkeleton rows={2} />);

    const status = screen.getByRole("status");
    expect(status.getAttribute("aria-busy")).toBe("true");
    expect(status.getAttribute("aria-label")).toContain("Загрузка");
  });

  it("иконку можно убрать — не у всех списков она есть", () => {
    const { container } = render(<ListSkeleton rows={3} withIcon={false} />);

    expect(container.querySelectorAll(".skeleton")).toHaveLength(3 * 2);
  });

  it("ширины заголовков стабильны между рендерами", () => {
    // Со Math.random() скелет «мерцал» бы при каждом ре-рендере вместо
    // спокойного ожидания — поэтому ширины заданы массивом.
    const widths = () =>
      Array.from(render(<ListSkeleton rows={6} />).container.querySelectorAll(".skeleton")).map(
        (el) => el.className,
      );

    expect(widths()).toEqual(widths());
  });

  it("сам блок не попадает в дерево доступности", () => {
    const { container } = render(<Skeleton className="h-4 w-4" />);

    expect(container.firstElementChild?.getAttribute("aria-hidden")).toBe("true");
  });
});

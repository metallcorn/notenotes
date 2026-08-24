import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ImageLightbox from "./ImageLightbox";

describe("ImageLightbox — эфемерный поворот (как в Telegram)", () => {
  it("клик по «Повернуть» вращает картинку и не закрывает просмотрщик", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<ImageLightbox images={[{ src: "/api/uploads/a" }]} onClose={onClose} />);

    const img = screen.getByRole("presentation");
    expect(img).toHaveStyle({ transform: "" });

    await user.click(screen.getByTitle("Повернуть на 90° (только для просмотра)"));

    expect(img).toHaveStyle({ transform: "rotate(90deg)" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it("четыре клика возвращают к 0° (полный цикл)", async () => {
    const user = userEvent.setup();
    render(<ImageLightbox images={[{ src: "/api/uploads/a" }]} onClose={vi.fn()} />);
    const button = screen.getByTitle("Повернуть на 90° (только для просмотра)");
    const img = screen.getByRole("presentation");

    await user.click(button);
    await user.click(button);
    await user.click(button);
    await user.click(button);

    expect(img).toHaveStyle({ transform: "" });
  });

  it("переход к следующей картинке сбрасывает поворот", async () => {
    const user = userEvent.setup();
    render(
      <ImageLightbox
        images={[{ src: "/api/uploads/a" }, { src: "/api/uploads/b" }]}
        onClose={vi.fn()}
      />,
    );

    await user.click(screen.getByTitle("Повернуть на 90° (только для просмотра)"));
    expect(screen.getByRole("presentation")).toHaveStyle({ transform: "rotate(90deg)" });

    await user.click(screen.getByTitle("Следующая картинка"));
    expect(screen.getByRole("presentation")).toHaveStyle({ transform: "" });
  });

  it("клик по фону/картинке (не по кнопке поворота) всё ещё закрывает просмотрщик", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<ImageLightbox images={[{ src: "/api/uploads/a" }]} onClose={onClose} />);

    await user.click(screen.getByRole("presentation"));
    expect(onClose).toHaveBeenCalled();
  });
});

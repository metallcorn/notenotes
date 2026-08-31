import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import LinkPreviewCard from "./LinkPreviewCard";
import type { NodeViewProps } from "@tiptap/react";

const hooks = vi.hoisted(() => ({ useLinkPreview: vi.fn() }));
vi.mock("../api/hooks", () => hooks);

function makeProps(url: string): NodeViewProps {
  return { node: { attrs: { url } } } as unknown as NodeViewProps;
}

describe("LinkPreviewCard", () => {
  it("пока грузится — обычная ссылка без иконки", () => {
    hooks.useLinkPreview.mockReturnValue({ data: undefined, isLoading: true });
    render(<LinkPreviewCard {...makeProps("https://example.com/x")} />);

    const link = screen.getByRole("link", { name: "https://example.com/x" });
    expect(link).toHaveAttribute("href", "https://example.com/x");
    expect(link).not.toHaveAttribute("title");
  });

  it(
    "реальная жалоба: fetch_failed (сайт требует авторизацию) — ссылка визуально " +
      "отличается от «просто не сработало», с иконкой и подсказкой",
    () => {
      hooks.useLinkPreview.mockReturnValue({ data: { fetch_failed: true }, isLoading: false });
      render(<LinkPreviewCard {...makeProps("https://allegro.pl/zamowienie/123")} />);

      const link = screen.getByRole("link");
      expect(link).toHaveAttribute("title", expect.stringContaining("Не удалось загрузить превью"));
    },
  );

  it("нет title в ответе (200, но без og:title) — тот же fallback с иконкой", () => {
    hooks.useLinkPreview.mockReturnValue({
      data: { fetch_failed: false, title: null, description: null, image_url: null, favicon_url: null },
      isLoading: false,
    });
    render(<LinkPreviewCard {...makeProps("https://example.com/x")} />);

    expect(screen.getByRole("link")).toHaveAttribute("title", expect.stringContaining("Не удалось загрузить превью"));
  });

  it("успешный fetch — богатая карточка с заголовком, без иконки-заглушки", () => {
    hooks.useLinkPreview.mockReturnValue({
      data: {
        fetch_failed: false,
        title: "Пример страницы",
        description: "Описание",
        image_url: null,
        favicon_url: null,
      },
      isLoading: false,
    });
    render(<LinkPreviewCard {...makeProps("https://example.com/x")} />);

    expect(screen.getByText("Пример страницы")).toBeInTheDocument();
    expect(screen.getByText("Описание")).toBeInTheDocument();
  });

  it(
    "реальная просьба: ссылка на YouTube — сразу плеер (iframe), " +
      "без похода на бэкенд за og:* метаданными",
    () => {
      // Хук вызывается всегда (правила хуков), даже когда embed-ветка
      // возвращает раньше, чем результат используется — mockReturnValue
      // нужен, чтобы деструктуризация { data, isLoading } не упала.
      hooks.useLinkPreview.mockReturnValue({ data: undefined, isLoading: false });
      render(<LinkPreviewCard {...makeProps("https://youtu.be/dQw4w9WgXcQ")} />);

      const iframe = document.querySelector("iframe");
      expect(iframe).toHaveAttribute("src", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ");
      expect(hooks.useLinkPreview).toHaveBeenCalledWith("https://youtu.be/dQw4w9WgXcQ", true);
    },
  );
});

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { createRef } from "react";
import NoteLinkSuggestionList, { type NoteLinkSuggestionListHandle } from "./NoteLinkSuggestionList";
import type { ItemTitleSearchResult } from "../api/types";

const apiMock = vi.hoisted(() => ({ api: { get: vi.fn() } }));
vi.mock("../api/client", () => apiMock);

function result(overrides: Partial<ItemTitleSearchResult> = {}): ItemTitleSearchResult {
  return { id: "i1", title: "Рецепт борща", space_id: "s1", material_type: "note", ...overrides };
}

describe("NoteLinkSuggestionList", () => {
  it("пустой query — не ходит в API, показывает подсказку набрать текст", () => {
    render(<NoteLinkSuggestionList query="" command={vi.fn()} />);
    expect(screen.getByText("Начните вводить название заметки…")).toBeInTheDocument();
    expect(apiMock.api.get).not.toHaveBeenCalled();
  });

  it("непустой query — дебаунсом идёт в /items/search-titles и показывает результаты", async () => {
    apiMock.api.get.mockResolvedValue([result()]);
    render(<NoteLinkSuggestionList query="борщ" command={vi.fn()} />);

    await waitFor(() => expect(apiMock.api.get).toHaveBeenCalledWith("/items/search-titles?q=%D0%B1%D0%BE%D1%80%D1%89"));
    await waitFor(() => expect(screen.getByText("Рецепт борща")).toBeInTheDocument());
  });

  it("ничего не найдено — соответствующее сообщение", async () => {
    apiMock.api.get.mockResolvedValue([]);
    render(<NoteLinkSuggestionList query="ничегонет" command={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Ничего не найдено")).toBeInTheDocument());
  });

  it("клик по результату вызывает command с этим элементом", async () => {
    const command = vi.fn();
    apiMock.api.get.mockResolvedValue([result()]);
    const user = userEvent.setup();
    render(<NoteLinkSuggestionList query="борщ" command={command} />);

    await waitFor(() => screen.getByText("Рецепт борща"));
    await user.click(screen.getByText("Рецепт борща"));
    expect(command).toHaveBeenCalledWith(result());
  });

  it("Enter выбирает текущий выделенный результат (клавиатурная навигация)", async () => {
    const command = vi.fn();
    apiMock.api.get.mockResolvedValue([result({ id: "i1", title: "Первый" }), result({ id: "i2", title: "Второй" })]);
    const ref = createRef<NoteLinkSuggestionListHandle>();
    render(<NoteLinkSuggestionList ref={ref} query="борщ" command={command} />);

    await waitFor(() => screen.getByText("Первый"));
    // setSelected — асинхронное обновление состояния; между стрелкой и
    // Enter нужен реальный ре-рендер, иначе Enter видит ещё старый selected.
    act(() => {
      ref.current!.onKeyDown({ event: new KeyboardEvent("keydown", { key: "ArrowDown" }) });
    });
    act(() => {
      ref.current!.onKeyDown({ event: new KeyboardEvent("keydown", { key: "Enter" }) });
    });

    expect(command).toHaveBeenCalledWith(expect.objectContaining({ id: "i2" }));
  });
});

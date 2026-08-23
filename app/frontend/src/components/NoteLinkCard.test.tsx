import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import NoteLinkCard from "./NoteLinkCard";
import type { NodeViewProps } from "@tiptap/react";
import type { Item } from "../api/types";

const hooks = vi.hoisted(() => ({ useItemBrief: vi.fn() }));
vi.mock("../api/hooks", () => hooks);

function makeProps(
  attrs: { itemId: string | null; title: string },
  onOpen = vi.fn(),
  updateAttributes = vi.fn(),
): NodeViewProps {
  return {
    node: { attrs },
    extension: { options: { onOpen } },
    updateAttributes,
  } as unknown as NodeViewProps;
}

describe("NoteLinkCard", () => {
  it("title уже известен ([[-автокомплит) — показывает его сразу, не ходит за данными", () => {
    hooks.useItemBrief.mockReturnValue({ data: undefined, isError: false });
    render(<NoteLinkCard {...makeProps({ itemId: "id-1", title: "Рецепт борща" })} />);

    expect(screen.getByText("Рецепт борща")).toBeInTheDocument();
    expect(hooks.useItemBrief).toHaveBeenCalledWith(undefined);
  });

  it("title пуст (вставлено голым URL) — подтягивает название по itemId и сохраняет в атрибут", async () => {
    hooks.useItemBrief.mockReturnValue({ data: { title: "Найденное название" } as Item, isError: false });
    const updateAttributes = vi.fn();
    render(<NoteLinkCard {...makeProps({ itemId: "id-1", title: "" }, vi.fn(), updateAttributes)} />);

    expect(hooks.useItemBrief).toHaveBeenCalledWith("id-1");
    expect(screen.getByText("Найденное название")).toBeInTheDocument();
    await waitFor(() => expect(updateAttributes).toHaveBeenCalledWith({ title: "Найденное название" }));
  });

  it("заметка недоступна (404/403) — показывает «Заметка недоступна», кнопка отключена", async () => {
    hooks.useItemBrief.mockReturnValue({ data: undefined, isError: true });
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(<NoteLinkCard {...makeProps({ itemId: "id-1", title: "" }, onOpen)} />);

    const button = screen.getByText("Заметка недоступна");
    expect(button.closest("button")).toBeDisabled();
    await user.click(button);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it("клик вызывает onOpen с itemId (переход внутри приложения)", async () => {
    hooks.useItemBrief.mockReturnValue({ data: undefined, isError: false });
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(<NoteLinkCard {...makeProps({ itemId: "id-42", title: "Т" }, onOpen)} />);

    await user.click(screen.getByText("Т"));
    expect(onOpen).toHaveBeenCalledWith("id-42");
  });
});

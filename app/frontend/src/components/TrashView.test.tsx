import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import TrashView from "./TrashView";
import type { Item } from "../api/types";

const hooks = vi.hoisted(() => ({
  useTrash: vi.fn(),
  useRestoreItem: vi.fn(),
  usePermanentDeleteItem: vi.fn(),
  useEmptyTrash: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

function mockMutation() {
  return { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };
}

function trashedItem(overrides: Partial<Item> = {}): Item {
  return {
    id: "i1",
    space_id: "s1",
    folder_id: null,
    author_id: "u1",
    material_type: "note",
    title: "Заметка",
    content: "",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    tags: [],
    icon: null,
    color: null,
    pinned: false,
    deleted_at: "2026-08-01T00:00:00Z",
    detected_addresses: [],
    ...overrides,
  };
}

describe("TrashView — очистка корзины", () => {
  it("пустая корзина — кнопки «Очистить корзину» нет", () => {
    hooks.useTrash.mockReturnValue({ data: [], isLoading: false });
    hooks.useRestoreItem.mockReturnValue(mockMutation());
    hooks.usePermanentDeleteItem.mockReturnValue(mockMutation());
    hooks.useEmptyTrash.mockReturnValue(mockMutation());

    render(<TrashView spaceId="s1" onBack={() => {}} />);

    expect(screen.queryByText("Очистить корзину")).not.toBeInTheDocument();
    expect(screen.getByText("Корзина пуста")).toBeInTheDocument();
  });

  it("непустая корзина — есть кнопка и упоминание 30-дневного срока", () => {
    hooks.useTrash.mockReturnValue({ data: [trashedItem()], isLoading: false });
    hooks.useRestoreItem.mockReturnValue(mockMutation());
    hooks.usePermanentDeleteItem.mockReturnValue(mockMutation());
    hooks.useEmptyTrash.mockReturnValue(mockMutation());

    render(<TrashView spaceId="s1" onBack={() => {}} />);

    expect(screen.getByText("Очистить корзину")).toBeInTheDocument();
    expect(screen.getByText(/через 30 дней/)).toBeInTheDocument();
  });

  it("клик по «Очистить корзину» → подтверждение → вызывает useEmptyTrash", async () => {
    const emptyMutation = mockMutation();
    hooks.useTrash.mockReturnValue({ data: [trashedItem()], isLoading: false });
    hooks.useRestoreItem.mockReturnValue(mockMutation());
    hooks.usePermanentDeleteItem.mockReturnValue(mockMutation());
    hooks.useEmptyTrash.mockReturnValue(emptyMutation);

    const user = userEvent.setup();
    render(<TrashView spaceId="s1" onBack={() => {}} />);

    await user.click(screen.getByText("Очистить корзину"));
    // Две кнопки с этим текстом на экране теперь: заголовочная и в
    // диалоге подтверждения (confirmLabel) — берём последнюю (диалог).
    const buttons = screen.getAllByRole("button", { name: "Очистить корзину" });
    await user.click(buttons[buttons.length - 1]);

    expect(emptyMutation.mutate).toHaveBeenCalled();
  });
});

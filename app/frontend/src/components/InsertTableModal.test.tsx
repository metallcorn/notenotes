import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import InsertTableModal from "./InsertTableModal";
import type { Item } from "../api/types";

const hooks = vi.hoisted(() => ({
  useCreateTable: vi.fn(),
  useItems: vi.fn(),
}));

vi.mock("../api/hooks", () => hooks);

function item(overrides: Partial<Item> = {}): Item {
  return {
    id: "item-1",
    space_id: "space-1",
    folder_id: null,
    author_id: "user-1",
    material_type: "table",
    title: "Расходы",
    content: "",
    icon: null,
    color: null,
    pinned: false,
    deleted_at: null,
    detected_addresses: [],
    tags: [],
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

describe("InsertTableModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.useItems.mockReturnValue({ data: [], isLoading: false });
  });

  it("defaults to the 'new table' mode with a title field and Создать button", () => {
    hooks.useCreateTable.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    render(<InsertTableModal spaceId="space-1" folderId={null} onInsert={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByPlaceholderText("Название таблицы")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Создать" })).toBeInTheDocument();
  });

  it("creates a new table with the typed title and inserts the returned id", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ id: "new-table-id" });
    hooks.useCreateTable.mockReturnValue({ mutateAsync, isPending: false });
    const onInsert = vi.fn();
    render(<InsertTableModal spaceId="space-1" folderId="folder-1" onInsert={onInsert} onCancel={vi.fn()} />);
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("Название таблицы"), "Бюджет");
    await user.click(screen.getByRole("button", { name: "Создать" }));
    expect(mutateAsync).toHaveBeenCalledWith({ space_id: "space-1", folder_id: "folder-1", title: "Бюджет" });
    expect(onInsert).toHaveBeenCalledWith("new-table-id");
  });

  it("creates a table with no title when the field is left empty", async () => {
    const mutateAsync = vi.fn().mockResolvedValue({ id: "new-table-id" });
    hooks.useCreateTable.mockReturnValue({ mutateAsync, isPending: false });
    render(<InsertTableModal spaceId="space-1" folderId={null} onInsert={vi.fn()} onCancel={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Создать" }));
    expect(mutateAsync).toHaveBeenCalledWith({ space_id: "space-1", folder_id: null, title: undefined });
  });

  it("switches to the existing-tables tab and lists only material_type=table items", async () => {
    hooks.useCreateTable.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    hooks.useItems.mockReturnValue({
      data: [item({ id: "t1", title: "Расходы" }), item({ id: "n1", title: "Заметка", material_type: "note" })],
      isLoading: false,
    });
    render(<InsertTableModal spaceId="space-1" folderId={null} onInsert={vi.fn()} onCancel={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Существующая" }));
    expect(screen.getByText("Расходы")).toBeInTheDocument();
    expect(screen.queryByText("Заметка")).not.toBeInTheDocument();
  });

  it("filters the existing-tables list by search query", async () => {
    hooks.useCreateTable.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    hooks.useItems.mockReturnValue({
      data: [item({ id: "t1", title: "Расходы" }), item({ id: "t2", title: "Подарки" })],
      isLoading: false,
    });
    render(<InsertTableModal spaceId="space-1" folderId={null} onInsert={vi.fn()} onCancel={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Существующая" }));
    await user.type(screen.getByPlaceholderText("Поиск по названию…"), "подар");
    expect(screen.getByText("Подарки")).toBeInTheDocument();
    expect(screen.queryByText("Расходы")).not.toBeInTheDocument();
  });

  it("clicking an existing table inserts its id directly, without creating a new one", async () => {
    const mutateAsync = vi.fn();
    hooks.useCreateTable.mockReturnValue({ mutateAsync, isPending: false });
    hooks.useItems.mockReturnValue({ data: [item({ id: "t1", title: "Расходы" })], isLoading: false });
    const onInsert = vi.fn();
    render(<InsertTableModal spaceId="space-1" folderId={null} onInsert={onInsert} onCancel={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Существующая" }));
    await user.click(screen.getByText("Расходы"));
    expect(onInsert).toHaveBeenCalledWith("t1");
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("shows an empty-state message when the space has no other tables", async () => {
    hooks.useCreateTable.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    hooks.useItems.mockReturnValue({ data: [], isLoading: false });
    render(<InsertTableModal spaceId="space-1" folderId={null} onInsert={vi.fn()} onCancel={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Существующая" }));
    expect(screen.getByText("В этом спейсе пока нет других таблиц")).toBeInTheDocument();
  });

  it("calls onCancel from either mode", async () => {
    hooks.useCreateTable.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    const onCancel = vi.fn();
    render(<InsertTableModal spaceId="space-1" folderId={null} onInsert={vi.fn()} onCancel={onCancel} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});

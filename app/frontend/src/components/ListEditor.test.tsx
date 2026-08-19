import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ListEditor, { renderEntryText } from "./ListEditor";
import type { ListDetail } from "../api/types";

const hooks = vi.hoisted(() => ({
  useList: vi.fn(),
  useAddListEntry: vi.fn(),
  useDeleteItem: vi.fn(),
  useDeleteListEntry: vi.fn(),
  useUpdateItem: vi.fn(),
  useUpdateListEntry: vi.fn(),
}));

vi.mock("../api/hooks", () => hooks);
vi.mock("../lib/useListSync", () => ({ useListSync: vi.fn() }));

function mockMutation() {
  return { mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false };
}

function baseList(overrides: Partial<ListDetail> = {}): ListDetail {
  return {
    id: "list-1",
    space_id: "space-1",
    folder_id: null,
    title: "Покупки",
    entries: [],
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

describe("renderEntryText", () => {
  it("renders a markdown link as a clickable anchor with link text only", () => {
    render(<div>{renderEntryText("Книга [магазин](https://example.com/product)")}</div>);
    const link = screen.getByRole("link", { name: "магазин" });
    expect(link).toHaveAttribute("href", "https://example.com/product");
    expect(screen.getByText(/Книга/)).toBeInTheDocument();
  });

  it("renders a bare URL as a link labeled by hostname, not the full URL", () => {
    render(<div>{renderEntryText("Смотри тут https://www.example.com/some/very/long/path")}</div>);
    const link = screen.getByRole("link", { name: "example.com" });
    expect(link).toHaveAttribute("href", "https://www.example.com/some/very/long/path");
  });

  it("renders plain text with no links as-is", () => {
    render(<div>{renderEntryText("Просто текст без ссылок")}</div>);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByText("Просто текст без ссылок")).toBeInTheDocument();
  });
});

describe("ListEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hooks.useAddListEntry.mockReturnValue(mockMutation());
    hooks.useDeleteItem.mockReturnValue(mockMutation());
    hooks.useDeleteListEntry.mockReturnValue(mockMutation());
    hooks.useUpdateItem.mockReturnValue(mockMutation());
    hooks.useUpdateListEntry.mockReturnValue(mockMutation());
  });

  it("shows a spinner while the list is loading", () => {
    hooks.useList.mockReturnValue({ data: undefined });
    render(<ListEditor itemId="list-1" onDeleted={vi.fn()} onBack={vi.fn()} />);
    expect(screen.queryByText("Пока пусто")).not.toBeInTheDocument();
  });

  it("shows the empty-state hint pointing at the input field when there are no entries", () => {
    hooks.useList.mockReturnValue({ data: baseList() });
    render(<ListEditor itemId="list-1" onDeleted={vi.fn()} onBack={vi.fn()} />);
    expect(screen.getByText("Пока пусто")).toBeInTheDocument();
    expect(screen.getByText(/Введите текст пункта в поле внизу/)).toBeInTheDocument();
  });

  it("clicking the empty-state hint focuses the new-entry input", async () => {
    hooks.useList.mockReturnValue({ data: baseList() });
    render(<ListEditor itemId="list-1" onDeleted={vi.fn()} onBack={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByText("Пока пусто"));
    expect(screen.getByPlaceholderText("Новый пункт…")).toHaveFocus();
  });

  it("renders entries with checkboxes reflecting their checked state", () => {
    hooks.useList.mockReturnValue({
      data: baseList({
        entries: [
          { id: "e1", text: "Молоко", checked: false, created_at: "2026-08-01T00:00:00Z" },
          { id: "e2", text: "Хлеб", checked: true, created_at: "2026-08-01T00:00:00Z" },
        ],
      }),
    });
    render(<ListEditor itemId="list-1" onDeleted={vi.fn()} onBack={vi.fn()} />);
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(2);
    expect(boxes[0]).not.toBeChecked();
    expect(boxes[1]).toBeChecked();
    expect(screen.getByText("1/2")).toBeInTheDocument();
  });

  it("toggling a checkbox calls the update mutation with the entry id and new state", async () => {
    const updateEntry = mockMutation();
    hooks.useUpdateListEntry.mockReturnValue(updateEntry);
    hooks.useList.mockReturnValue({
      data: baseList({ entries: [{ id: "e1", text: "Молоко", checked: false, created_at: "2026-08-01T00:00:00Z" }] }),
    });
    render(<ListEditor itemId="list-1" onDeleted={vi.fn()} onBack={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox"));
    expect(updateEntry.mutate).toHaveBeenCalledWith({ entryId: "e1", checked: true });
  });

  it("deleting an entry calls the delete mutation with the entry id", async () => {
    const deleteEntry = mockMutation();
    hooks.useDeleteListEntry.mockReturnValue(deleteEntry);
    hooks.useList.mockReturnValue({
      data: baseList({ entries: [{ id: "e1", text: "Молоко", checked: false, created_at: "2026-08-01T00:00:00Z" }] }),
    });
    render(<ListEditor itemId="list-1" onDeleted={vi.fn()} onBack={vi.fn()} />);
    const user = userEvent.setup();
    await user.click(screen.getByTitle("Удалить пункт"));
    expect(deleteEntry.mutate).toHaveBeenCalledWith("e1");
  });

  it("submitting the new-entry form adds a trimmed entry and clears the input", async () => {
    const addEntry = mockMutation();
    hooks.useAddListEntry.mockReturnValue(addEntry);
    hooks.useList.mockReturnValue({ data: baseList() });
    render(<ListEditor itemId="list-1" onDeleted={vi.fn()} onBack={vi.fn()} />);
    const user = userEvent.setup();
    const input = screen.getByPlaceholderText("Новый пункт…");
    await user.type(input, "  Сыр  ");
    const form = input.closest("form")!;
    await user.click(within(form).getByRole("button"));
    expect(addEntry.mutateAsync).toHaveBeenCalledWith("Сыр");
  });

  it("does not submit an empty or whitespace-only entry", async () => {
    const addEntry = mockMutation();
    hooks.useAddListEntry.mockReturnValue(addEntry);
    hooks.useList.mockReturnValue({ data: baseList() });
    render(<ListEditor itemId="list-1" onDeleted={vi.fn()} onBack={vi.fn()} />);
    const user = userEvent.setup();
    const input = screen.getByPlaceholderText("Новый пункт…");
    await user.type(input, "   ");
    const submitButton = within(input.closest("form")!).getByRole("button");
    expect(submitButton).toBeDisabled();
    expect(addEntry.mutateAsync).not.toHaveBeenCalled();
  });
});

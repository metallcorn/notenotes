import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { Folder, Item, Space } from "../api/types";

const hooks = vi.hoisted(() => ({
  useFolders: vi.fn(),
  useItems: vi.fn(),
  useSpaceMembers: vi.fn(),
  useUpdateFolder: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useDeleteFolder: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useCreateFolder: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
  useSpaces: vi.fn(() => ({ data: [] })),
  useMoveFolderSpace: vi.fn(() => ({ mutateAsync: vi.fn(), isPending: false })),
}));
vi.mock("../api/hooks", () => hooks);
vi.mock("./SpaceMembersModal", () => ({ default: () => null }));
vi.mock("./VaultUnlockOverlay", () => ({ default: () => <div>замок</div> }));

import SpaceFoldersScreen from "./SpaceFoldersScreen";

const space: Space = { id: "s1", name: "Семейный", owner_id: "u1", created_at: "", is_vault: false, is_public_pages: false };
const folder = (o: Partial<Folder>): Folder => ({ id: "f", space_id: "s1", parent_id: null, name: "Папка", icon: null, created_at: "", ...o });
const item = (o: Partial<Item>): Item =>
  ({ id: "i", space_id: "s1", folder_id: null, material_type: "note", title: "", content: "", tags: [], icon: null, color: null, pinned: false, deleted_at: null, detected_addresses: [], created_at: "", updated_at: "", author_id: "u1", ...o }) as Item;

describe("SpaceFoldersScreen — экран папок спейса на телефоне", () => {
  it("считает заметки в карточках и у папок, показывает значок папки", () => {
    hooks.useFolders.mockReturnValue({
      data: [folder({ id: "trips", name: "Поездки", icon: "✈️" }), folder({ id: "rome", name: "Рим", parent_id: "trips" })],
    });
    hooks.useItems.mockReturnValue({
      data: [item({ id: "1" }), item({ id: "2", folder_id: "trips" }), item({ id: "3", folder_id: "trips" }), item({ id: "4", folder_id: "rome" })],
    });
    hooks.useSpaceMembers.mockReturnValue({ data: [{ user_id: "u1" }, { user_id: "u2" }] });
    const onSelectFolder = vi.fn();
    render(<SpaceFoldersScreen space={space} selectedFolderId={null} onSelectFolder={onSelectFolder} onOpenSpaces={() => {}} />);

    expect(screen.getByRole("button", { name: /Все заметки/ })).toHaveTextContent("4");
    expect(screen.getByRole("button", { name: /Без папки/ })).toHaveTextContent("1");
    const trips = screen.getByRole("button", { name: /Поездки/ });
    expect(trips).toHaveTextContent("✈️");
    expect(trips).toHaveTextContent("2");
    // Подпапка свёрнута, раскрывается шевроном.
    expect(screen.queryByText("Рим")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Развернуть" }));
    expect(screen.getByText("Рим")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Без папки/ }));
    expect(onSelectFolder).toHaveBeenCalledWith("root");
    fireEvent.click(trips);
    expect(onSelectFolder).toHaveBeenCalledWith("trips");
  });

  it("долгое нажатие открывает шторку действий, а следующий клик не открывает папку", () => {
    vi.useFakeTimers();
    hooks.useFolders.mockReturnValue({ data: [folder({ id: "home", name: "Квартира" })] });
    hooks.useItems.mockReturnValue({ data: [] });
    hooks.useSpaceMembers.mockReturnValue({ data: [] });
    const onSelectFolder = vi.fn();
    render(<SpaceFoldersScreen space={space} selectedFolderId={null} onSelectFolder={onSelectFolder} onOpenSpaces={() => {}} />);
    const row = screen.getByRole("button", { name: /Квартира/ });
    fireEvent.pointerDown(row, { clientX: 10, clientY: 10, pointerType: "touch", button: 0 });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    fireEvent.pointerUp(row);
    fireEvent.click(row);
    expect(onSelectFolder).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog", { name: "Действия с папкой" })).toBeInTheDocument();
    expect(screen.getByText("Подпапка")).toBeInTheDocument();
    expect(screen.getByText("Удалить")).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("сейф закрыт — вместо папок форма разблокировки", () => {
    hooks.useFolders.mockReturnValue({ data: undefined });
    hooks.useItems.mockReturnValue({ data: undefined });
    hooks.useSpaceMembers.mockReturnValue({ data: [] });
    render(
      <SpaceFoldersScreen space={{ ...space, is_vault: true }} selectedFolderId={null} onSelectFolder={() => {}} onOpenSpaces={() => {}} />,
    );
    expect(screen.getByText("замок")).toBeInTheDocument();
    expect(screen.queryByText("Папки")).toBeNull();
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import NoteList, { listProgress, previewText } from "./NoteList";
import type { DialogSummary, Item } from "../api/types";

const hooks = vi.hoisted(() => ({
  useItems: vi.fn(),
  useCreateItem: vi.fn(),
  useCreateList: vi.fn(),
  useCreateTable: vi.fn(),
  useCreateDialog: vi.fn(),
  useScopedFolderDialogs: vi.fn(),
  useDeleteItem: vi.fn(),
  useUpdateItem: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  useArchiveItem: vi.fn(() => ({ mutate: vi.fn(), isPending: false })),
  // Кнопка «Новая рутина» в шапке списка ищет текущий спейс (26.10).
  useSpaces: vi.fn(() => ({ data: [] })),
}));
vi.mock("../api/hooks", () => hooks);

function mockMutation(overrides: Partial<{ mutateAsync: (...args: unknown[]) => Promise<unknown> }> = {}) {
  return { mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false, ...overrides };
}

function dialogSummary(overrides: Partial<DialogSummary> = {}): DialogSummary {
  return {
    id: "d1",
    space_id: "s1",
    space_name: "S",
    title: "Ассистент: папка «Авто»",
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    preview: "Что по ТО?",
    ...overrides,
  };
}

describe("previewText", () => {
  it("strips HTML tags", () => {
    expect(previewText("<b>Привет</b> мир")).toBe("Привет мир");
  });

  it("strips markdown images entirely", () => {
    expect(previewText("Текст ![alt](/api/uploads/abc) продолжение")).toBe("Текст продолжение");
  });

  it("keeps link text but drops the URL", () => {
    expect(previewText("Смотри [сюда](https://example.com)")).toBe("Смотри сюда");
  });

  it("strips markdown formatting characters", () => {
    expect(previewText("# Заголовок\n\n**жирный** и _курсив_")).toBe("Заголовок жирный и курсив");
  });

  it("collapses whitespace and truncates to 120 chars", () => {
    const long = "a".repeat(200);
    const result = previewText(long);
    expect(result).toHaveLength(120);
  });

  it("returns empty string for empty content", () => {
    expect(previewText("")).toBe("");
  });
});

describe("listProgress", () => {
  it("returns 'Пусто' for empty content", () => {
    expect(listProgress("")).toBe("Пусто");
  });

  it("counts done vs total lines", () => {
    expect(listProgress("[x] Молоко\n[ ] Хлеб\n[x] Сыр")).toBe("2/3 выполнено");
  });

  it("counts zero done when nothing is checked", () => {
    expect(listProgress("[ ] Молоко\n[ ] Хлеб")).toBe("0/2 выполнено");
  });

  it("ignores blank lines", () => {
    expect(listProgress("[x] Молоко\n\n[ ] Хлеб")).toBe("1/2 выполнено");
  });
});

describe("NoteList — «Обсудить с ассистентом»", () => {
  function setup(overrides: { createDialog?: ReturnType<typeof mockMutation>; scopedFolderDialogs?: ReturnType<typeof mockMutation> } = {}) {
    hooks.useItems.mockReturnValue({ data: [] as Item[], isLoading: false });
    hooks.useCreateItem.mockReturnValue(mockMutation());
    hooks.useCreateList.mockReturnValue(mockMutation());
    hooks.useCreateTable.mockReturnValue(mockMutation());
    hooks.useCreateDialog.mockReturnValue(overrides.createDialog ?? mockMutation());
    hooks.useScopedFolderDialogs.mockReturnValue(overrides.scopedFolderDialogs ?? mockMutation());
    hooks.useDeleteItem.mockReturnValue(mockMutation());
  }

  it("не показывается для «Все заметки» (folderId=null)", () => {
    setup();
    render(<NoteList spaceId="s1" folderId={null} tagId={null} selectedId={null} onSelect={vi.fn()} onSelectDialog={vi.fn()} />);
    expect(screen.queryByText("Обсудить с ассистентом")).not.toBeInTheDocument();
  });

  it("не показывается для «Без папки» (folderId=\"root\")", () => {
    setup();
    render(<NoteList spaceId="s1" folderId="root" tagId={null} selectedId={null} onSelect={vi.fn()} onSelectDialog={vi.fn()} />);
    expect(screen.queryByText("Обсудить с ассистентом")).not.toBeInTheDocument();
  });

  it("не показывается в режиме тега, даже если folderId задан", () => {
    setup();
    render(<NoteList spaceId="s1" folderId="f1" tagId="t1" selectedId={null} onSelect={vi.fn()} onSelectDialog={vi.fn()} />);
    expect(screen.queryByText("Обсудить с ассистентом")).not.toBeInTheDocument();
  });

  it("показывается для реальной папки", () => {
    setup();
    render(<NoteList spaceId="s1" folderId="f1" tagId={null} selectedId={null} onSelect={vi.fn()} onSelectDialog={vi.fn()} />);
    expect(screen.getByText("Обсудить с ассистентом")).toBeInTheDocument();
  });

  it("клик при 0 прошлых диалогов сразу создаёт новый и вызывает onSelectDialog", async () => {
    const createDialog = mockMutation({ mutateAsync: vi.fn().mockResolvedValue({ id: "new-dialog" }) });
    const scopedFolderDialogs = mockMutation({ mutateAsync: vi.fn().mockResolvedValue([]) });
    setup({ createDialog, scopedFolderDialogs });
    const onSelectDialog = vi.fn();
    const user = userEvent.setup();

    render(<NoteList spaceId="s1" folderId="f1" tagId={null} selectedId={null} onSelect={vi.fn()} onSelectDialog={onSelectDialog} />);
    await user.click(screen.getByText("Обсудить с ассистентом"));

    expect(scopedFolderDialogs.mutateAsync).toHaveBeenCalledWith("f1");
    await waitFor(() => expect(createDialog.mutateAsync).toHaveBeenCalledWith({ scoped_folder_id: "f1" }));
    await waitFor(() => expect(onSelectDialog).toHaveBeenCalledWith("new-dialog"));
    expect(screen.queryByText("Новый диалог")).not.toBeInTheDocument();
  });

  it("клик при 1+ прошлых диалогах открывает пикер вместо немедленного создания", async () => {
    const createDialog = mockMutation();
    const scopedFolderDialogs = mockMutation({ mutateAsync: vi.fn().mockResolvedValue([dialogSummary()]) });
    setup({ createDialog, scopedFolderDialogs });
    const user = userEvent.setup();

    render(<NoteList spaceId="s1" folderId="f1" tagId={null} selectedId={null} onSelect={vi.fn()} onSelectDialog={vi.fn()} />);
    await user.click(screen.getByText("Обсудить с ассистентом"));

    await waitFor(() => expect(screen.getByText("Что по ТО?")).toBeInTheDocument());
    expect(screen.getByText("Новый диалог")).toBeInTheDocument();
    expect(createDialog.mutateAsync).not.toHaveBeenCalled();
  });

  it("выбор диалога из пикера вызывает onSelectDialog с его id", async () => {
    const scopedFolderDialogs = mockMutation({ mutateAsync: vi.fn().mockResolvedValue([dialogSummary({ id: "old-dialog" })]) });
    setup({ scopedFolderDialogs });
    const onSelectDialog = vi.fn();
    const user = userEvent.setup();

    render(<NoteList spaceId="s1" folderId="f1" tagId={null} selectedId={null} onSelect={vi.fn()} onSelectDialog={onSelectDialog} />);
    await user.click(screen.getByText("Обсудить с ассистентом"));
    await waitFor(() => screen.getByText("Что по ТО?"));
    await user.click(screen.getByText("Что по ТО?"));

    expect(onSelectDialog).toHaveBeenCalledWith("old-dialog");
  });

  it("«Новый диалог» в пикере создаёт новый и вызывает onSelectDialog", async () => {
    const createDialog = mockMutation({ mutateAsync: vi.fn().mockResolvedValue({ id: "new-dialog" }) });
    const scopedFolderDialogs = mockMutation({ mutateAsync: vi.fn().mockResolvedValue([dialogSummary()]) });
    setup({ createDialog, scopedFolderDialogs });
    const onSelectDialog = vi.fn();
    const user = userEvent.setup();

    render(<NoteList spaceId="s1" folderId="f1" tagId={null} selectedId={null} onSelect={vi.fn()} onSelectDialog={onSelectDialog} />);
    await user.click(screen.getByText("Обсудить с ассистентом"));
    await waitFor(() => screen.getByText("Новый диалог"));
    await user.click(screen.getByText("Новый диалог"));

    expect(createDialog.mutateAsync).toHaveBeenCalledWith({ scoped_folder_id: "f1" });
    await waitFor(() => expect(onSelectDialog).toHaveBeenCalledWith("new-dialog"));
  });

  // Реальная жалоба: "эти чаты нельзя удалять почему-то" — у пикера чатов
  // по папке не было кнопки удаления, хотя у аналогичных списков
  // (NoteAssistantModal.tsx, DialogList.tsx) она уже есть.
  it("удаление диалога в пикере зовёт deleteItem и убирает его из списка", async () => {
    const deleteItem = mockMutation();
    const scopedFolderDialogs = mockMutation({ mutateAsync: vi.fn().mockResolvedValue([dialogSummary({ id: "old-dialog" })]) });
    // Единственный чат в пикере удаляется — компонент тут же создаёт новый
    // взамен (см. onDeleted в NoteList.tsx), поэтому createDialog тоже
    // должен реально резолвиться, не в undefined по умолчанию.
    const createDialog = mockMutation({ mutateAsync: vi.fn().mockResolvedValue({ id: "fallback-dialog" }) });
    setup({ scopedFolderDialogs, createDialog });
    hooks.useDeleteItem.mockReturnValue(deleteItem);
    const user = userEvent.setup();

    render(<NoteList spaceId="s1" folderId="f1" tagId={null} selectedId={null} onSelect={vi.fn()} onSelectDialog={vi.fn()} />);
    await user.click(screen.getByText("Обсудить с ассистентом"));
    await waitFor(() => screen.getByText("Что по ТО?"));

    await user.click(screen.getByTitle("Удалить диалог"));
    await user.click(screen.getByText("Удалить"));

    await waitFor(() => expect(deleteItem.mutateAsync).toHaveBeenCalledWith("old-dialog"));
    await waitFor(() => expect(screen.queryByText("Что по ТО?")).not.toBeInTheDocument());
  });
});

describe("NoteList — меню шаблонов «+Заметка» не обрезается панелью спейсов", () => {
  it("рендерится порталом в document.body (вне overflow-hidden предка)", async () => {
    hooks.useItems.mockReturnValue({ data: [] as Item[], isLoading: false });
    hooks.useCreateItem.mockReturnValue(mockMutation());
    hooks.useCreateList.mockReturnValue(mockMutation());
    hooks.useCreateTable.mockReturnValue(mockMutation());
    hooks.useCreateDialog.mockReturnValue(mockMutation());
    hooks.useScopedFolderDialogs.mockReturnValue(mockMutation());
    const user = userEvent.setup();

    // Тот же сценарий, что реальная жалоба: панель спейсов — соседний
    // overflow-y-auto скролл-контейнер, обрезающий абс-позиционированное
    // выпадающее меню — воспроизводим клипающего предка напрямую, как
    // в FolderTree.test.tsx.
    const { container } = render(
      <div style={{ overflow: "hidden", height: 50 }} data-testid="clipping-ancestor">
        <NoteList spaceId="s1" folderId={null} tagId={null} selectedId={null} onSelect={vi.fn()} onSelectDialog={vi.fn()} />
      </div>,
    );

    // Десктопная и мобильная кнопки рендерятся в DOM одновременно (видимость
    // переключает только Tailwind hidden/md:flex, jsdom это не считает) —
    // берём первую (десктопную, align="top").
    await user.click(screen.getAllByTitle("Шаблон заметки")[0]);

    const clippingAncestor = container.querySelector('[data-testid="clipping-ancestor"]');
    const menuItem = screen.getByText("Встреча");
    expect(clippingAncestor?.contains(menuItem)).toBe(false);
    expect(document.body.contains(menuItem)).toBe(true);
  });
});

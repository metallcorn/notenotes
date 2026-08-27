import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import AssistantChat from "./AssistantChat";
import type { Dialog, DialogMessage } from "../api/types";

// jsdom не реализует scrollIntoView — компонент дёргает его в эффекте на
// каждый рендер списка сообщений (автоскролл вниз), без полифилла падает.
Element.prototype.scrollIntoView = vi.fn();

const hooks = vi.hoisted(() => ({
  useDialog: vi.fn(),
  useSendDialogMessage: vi.fn(),
  useDeleteDialogMessage: vi.fn(),
  useCompactDialog: vi.fn(),
  useRevertCompaction: vi.fn(),
  useUpdateItem: vi.fn(),
  useUploadFile: vi.fn(),
  useDescribeUploadNow: vi.fn(),
  useSpeak: vi.fn(),
  useLinkPreview: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

function mockMutation(overrides: Partial<{ mutate: (...args: unknown[]) => void; isPending: boolean }> = {}) {
  return { mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false, ...overrides };
}

let _msgCounter = 0;

function msg(overrides: Partial<DialogMessage> = {}): DialogMessage {
  return {
    id: `m${_msgCounter++}`,
    role: "user",
    content: "текст",
    tool_calls: [],
    display_tool_calls: [],
    tool_call_id: null,
    name: null,
    suggested_replies: [],
    created_at: "2026-08-26T00:00:00Z",
    is_summary: false,
    snapshot_id: null,
    ...overrides,
  };
}

function dialog(messages: DialogMessage[], overrides: Partial<Dialog> = {}): Dialog {
  return {
    id: "d1",
    space_id: "s1",
    space_name: "S",
    title: "Диалог",
    created_at: "2026-08-26T00:00:00Z",
    updated_at: "2026-08-26T00:00:00Z",
    messages,
    compaction_snapshots: [],
    ...overrides,
  };
}

function setupCommonMocks() {
  hooks.useSendDialogMessage.mockReturnValue(mockMutation());
  hooks.useDeleteDialogMessage.mockReturnValue(mockMutation());
  hooks.useUpdateItem.mockReturnValue(mockMutation());
  hooks.useUploadFile.mockReturnValue(mockMutation());
  hooks.useDescribeUploadNow.mockReturnValue(mockMutation());
  hooks.useSpeak.mockReturnValue(mockMutation());
  hooks.useLinkPreview.mockReturnValue({ data: undefined, isLoading: false });
}

function renderChat() {
  const qc = new QueryClient();
  return render(
    <QueryClientProvider client={qc}>
      <AssistantChat dialogId="d1" onBack={vi.fn()} onOpenItem={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("AssistantChat — сжатие истории", () => {
  it("подсказка-баннер не показывается при малом числе сообщений", () => {
    setupCommonMocks();
    hooks.useCompactDialog.mockReturnValue(mockMutation());
    hooks.useRevertCompaction.mockReturnValue(mockMutation());
    hooks.useDialog.mockReturnValue({ data: dialog([msg(), msg({ role: "assistant" })]) });

    renderChat();

    expect(screen.queryByText(/каждый ответ становится медленнее/)).not.toBeInTheDocument();
  });

  it("баннер показывается при >60 сообщений и скрывается по кнопке закрытия", async () => {
    setupCommonMocks();
    hooks.useCompactDialog.mockReturnValue(mockMutation());
    hooks.useRevertCompaction.mockReturnValue(mockMutation());
    const messages = Array.from({ length: 61 }, (_, i) => msg({ role: i % 2 === 0 ? "user" : "assistant" }));
    hooks.useDialog.mockReturnValue({ data: dialog(messages) });
    const user = userEvent.setup();

    renderChat();

    const banner = screen.getByText(/каждый ответ становится медленнее/).closest("div")!;
    expect(banner).toBeInTheDocument();
    await user.click(within(banner).getByTitle("Скрыть подсказку"));
    expect(screen.queryByText(/каждый ответ становится медленнее/)).not.toBeInTheDocument();
  });

  it("кнопка «Сжать историю» в шапке открывает подтверждение, подтверждение вызывает compactDialog.mutate", async () => {
    setupCommonMocks();
    const compactDialog = mockMutation();
    hooks.useCompactDialog.mockReturnValue(compactDialog);
    hooks.useRevertCompaction.mockReturnValue(mockMutation());
    const messages = Array.from({ length: 15 }, () => msg());
    hooks.useDialog.mockReturnValue({ data: dialog(messages) });
    const user = userEvent.setup();

    renderChat();

    await user.click(screen.getByTitle("Сжать историю"));
    expect(screen.getByText(/Сжать более раннюю часть истории/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Сжать" }));

    expect(compactDialog.mutate).toHaveBeenCalledWith(undefined);
  });

  it("кнопка «Сжать историю» отключена, если сообщений меньше 10", () => {
    setupCommonMocks();
    hooks.useCompactDialog.mockReturnValue(mockMutation());
    hooks.useRevertCompaction.mockReturnValue(mockMutation());
    hooks.useDialog.mockReturnValue({ data: dialog([msg(), msg()]) });

    renderChat();

    expect(screen.getByTitle("Сжать историю")).toBeDisabled();
  });

  it("сводное сообщение рендерится отдельной карточкой, «Отменить сжатие» вызывает revertCompaction.mutate", async () => {
    setupCommonMocks();
    hooks.useCompactDialog.mockReturnValue(mockMutation());
    const revertCompaction = mockMutation();
    hooks.useRevertCompaction.mockReturnValue(revertCompaction);
    const summary = msg({
      role: "assistant",
      content: "Раньше обсуждали тренировки ног и спины",
      is_summary: true,
      snapshot_id: "snap-1",
    });
    hooks.useDialog.mockReturnValue({ data: dialog([summary, msg({ role: "user" })]) });
    const user = userEvent.setup();

    renderChat();

    expect(screen.getByText("Сводка более ранней части разговора")).toBeInTheDocument();
    expect(screen.getByText("Раньше обсуждали тренировки ног и спины")).toBeInTheDocument();
    await user.click(screen.getByText("Отменить сжатие"));

    expect(revertCompaction.mutate).toHaveBeenCalledWith("snap-1");
  });
});

describe("AssistantChat — переключатель технических деталей вызовов инструментов", () => {
  it("чипы вызовов инструментов скрыты по умолчанию, переключатель их показывает", async () => {
    localStorage.clear();
    setupCommonMocks();
    hooks.useCompactDialog.mockReturnValue(mockMutation());
    hooks.useRevertCompaction.mockReturnValue(mockMutation());
    const withTool = msg({
      role: "assistant",
      content: "Готово",
      tool_calls: [{ id: "c1", name: "search_base", arguments: {} }],
    });
    hooks.useDialog.mockReturnValue({ data: dialog([msg(), withTool]) });
    const user = userEvent.setup();

    renderChat();

    expect(screen.queryByText("search_base")).not.toBeInTheDocument();
    await user.click(screen.getByTitle("Показать технические детали вызовов инструментов"));
    expect(screen.getByText("search_base")).toBeInTheDocument();

    localStorage.clear();
  });
});

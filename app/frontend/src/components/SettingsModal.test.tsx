import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsModal from "./SettingsModal";

/**
 * Окно настроек разрослось до одиннадцати разделов в одном свитке —
 * «Память ассистента» лежала под «Инвайт-кодами», и добраться до неё
 * означало прокрутить всё. Разделы разнесены по вкладкам с переходом
 * слева.
 *
 * Здесь проверяется только навигация: содержимое каждого раздела покрыто
 * своими тестами (McpSettings.test.tsx и остальные).
 */

const hooks = vi.hoisted(() => {
  const idle = { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };
  const empty = { data: [], isLoading: false };
  return {
    useMe: vi.fn(() => ({ data: { llm_provider: "", timezone: "Europe/Warsaw", digest_time: "09:00" } })),
    useMemories: vi.fn(() => empty),
    useAddMemory: vi.fn(() => idle),
    useDeleteMemory: vi.fn(() => idle),
    useSkills: vi.fn(() => empty),
    useUpdateDisabledTools: vi.fn(() => idle),
    useUpdateCustomInstructions: vi.fn(() => idle),
    useUpdateLlmProvider: vi.fn(() => idle),
    useUpdateTimezone: vi.fn(() => idle),
    useUpdateDigestTime: vi.fn(() => idle),
    useUpdateTtsVoice: vi.fn(() => idle),
    useUpdateAutoProcessUploads: vi.fn(() => idle),
    useInviteCodes: vi.fn(() => empty),
    useCreateInviteCode: vi.fn(() => idle),
    useTelegramStatus: vi.fn(() => ({ data: { linked: false } })),
    useTelegramLinkCode: vi.fn(() => idle),
    useTelegramUnlink: vi.fn(() => idle),
    useMailStatus: vi.fn(() => ({ data: { enabled: false, addresses: [] } })),
    useGenerateMailAddress: vi.fn(() => idle),
    useRegenerateMailAddress: vi.fn(() => idle),
    useDisableMailInbox: vi.fn(() => idle),
    useAddOwnMailAddress: vi.fn(() => idle),
    useRemoveOwnMailAddress: vi.fn(() => idle),
    useMcpTokens: vi.fn(() => empty),
    useCreateMcpToken: vi.fn(() => idle),
    useRevokeMcpToken: vi.fn(() => idle),
    useOAuthConnections: vi.fn(() => ({ data: [] })),
    useRevokeOAuthConnection: vi.fn(() => idle),
    useMcpAudit: vi.fn(() => ({ data: [] })),
  };
});
vi.mock("../api/hooks", () => hooks);
// IndexedDB в jsdom нет — без заглушки эффект «прочитать лимит кэша»
// сыплет посторонними ошибками поверх результатов.
vi.mock("../lib/offlineSettings", () => ({
  DEFAULT_MEDIA_CACHE_LIMIT_MB: 200,
  getMediaCacheLimitBytes: vi.fn(async () => 200 * 1024 * 1024),
  setMediaCacheLimitMb: vi.fn(async () => {}),
}));
vi.mock("../lib/usePushSubscription", () => ({
  isPushSupported: () => false,
  usePushSubscription: () => ({ subscribed: false, subscribe: vi.fn(), unsubscribe: vi.fn(), busy: false }),
}));

beforeEach(() => vi.clearAllMocks());

describe("переход по разделам", () => {
  it("сначала открыт «Ассистент»", () => {
    render(<SettingsModal onClose={vi.fn()} />);

    expect(screen.getByText("Дополнительные инструкции")).toBeInTheDocument();
    // Разделы разнесены: «Почта» лежит в «Каналах» и сейчас не показана.
    expect(screen.queryByText("Почта")).not.toBeInTheDocument();
  });

  it("клик по разделу показывает его и прячет прежний", async () => {
    render(<SettingsModal onClose={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /Каналы/ }));

    expect(screen.getByText("Почта")).toBeInTheDocument();
    expect(screen.queryByText("Дополнительные инструкции")).not.toBeInTheDocument();
  });

  it("подключения по MCP лежат в своём разделе", async () => {
    // Раньше секция была одиннадцатой в общем свитке — до неё надо было
    // долистать.
    render(<SettingsModal onClose={vi.fn()} />);

    await userEvent.click(screen.getByRole("button", { name: /Подключения/ }));

    expect(screen.getByText("Подключение по MCP")).toBeInTheDocument();
  });

  it("все четыре раздела доступны с первого экрана", () => {
    render(<SettingsModal onClose={vi.fn()} />);

    for (const label of ["Ассистент", "Каналы", "Подключения", "Приложение"]) {
      expect(screen.getByRole("button", { name: new RegExp(label) })).toBeInTheDocument();
    }
  });
});

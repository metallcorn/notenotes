import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import McpSettings from "./McpSettings";

const hooks = vi.hoisted(() => ({
  useMcpTokens: vi.fn(),
  useCreateMcpToken: vi.fn(),
  useRevokeMcpToken: vi.fn(),
  useOAuthConnections: vi.fn(),
  useRevokeOAuthConnection: vi.fn(),
  useMcpAudit: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

function setup(
  tokens: unknown[] = [],
  created = { token: "nn_секрет123", id: "t1", name: "" },
  connections: unknown[] = [],
  auditEntries: unknown[] | undefined = [],
) {
  const mutateAsync = vi.fn().mockResolvedValue(created);
  const revoke = vi.fn();
  const revokeConn = vi.fn();
  hooks.useMcpTokens.mockReturnValue({ data: tokens, isLoading: false });
  hooks.useCreateMcpToken.mockReturnValue({ mutateAsync, isPending: false });
  hooks.useRevokeMcpToken.mockReturnValue({ mutate: revoke, isPending: false });
  hooks.useOAuthConnections.mockReturnValue({ data: connections });
  hooks.useRevokeOAuthConnection.mockReturnValue({ mutate: revokeConn, isPending: false });
  hooks.useMcpAudit.mockReturnValue({ data: auditEntries });
  render(<McpSettings />);
  return { mutateAsync, revoke, revokeConn };
}

beforeEach(() => {
  vi.clearAllMocks();
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } });
});

describe("предупреждение о том, куда уходят заметки", () => {
  it("видно до всякого создания токена", () => {
    // Токен отдаёт содержимое базы наружу. Человек должен прочитать это
    // ДО того, как нажмёт кнопку, а не узнать потом.
    setup();
    expect(screen.getByText(/не готовы показать базу целиком/)).toBeInTheDocument();
    expect(screen.getByText(/сейф недоступен всегда/)).toBeInTheDocument();
  });
});

describe("создание токена", () => {
  it("показывает токен и готовую команду", async () => {
    const { mutateAsync } = setup();

    await userEvent.type(screen.getByPlaceholderText(/ноутбук/), "ноутбук");
    await userEvent.click(screen.getByRole("button", { name: "" }).closest("button")!);

    await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith("ноутбук"));
    expect(await screen.findByText("nn_секрет123")).toBeInTheDocument();
    // Готовая строка для вставки: без неё человеку пришлось бы собирать
    // команду руками и ошибаться в URL.
    expect(screen.getByText(/claude mcp add -t http notenotes/)).toBeInTheDocument();
  });

  it("предупреждает, что токен показан один раз", async () => {
    setup();
    await userEvent.click(screen.getByRole("button", { name: "" }).closest("button")!);

    // На сервере лежит только хэш — восстановить нечего, и человек должен
    // это понимать до того, как закроет окно.
    expect(await screen.findByText(/показан один раз/)).toBeInTheDocument();
  });
});

describe("список подключений", () => {
  it("показывает, когда токеном пользовались", () => {
    setup([
      { id: "a", name: "ноутбук", created_at: "2026-09-10T10:00:00Z", last_used_at: "2026-09-10T12:00:00Z" },
      { id: "b", name: "телефон", created_at: "2026-09-10T10:00:00Z", last_used_at: null },
    ]);

    expect(screen.getByText("ноутбук")).toBeInTheDocument();
    // Единственный способ заметить забытый токен и отозвать его.
    expect(screen.getByText(/Последний раз:/)).toBeInTheDocument();
    expect(screen.getByText("Ещё не использовался")).toBeInTheDocument();
  });

  it("отзывает по кнопке", async () => {
    const { revoke } = setup([
      { id: "a", name: "ноутбук", created_at: "2026-09-10T10:00:00Z", last_used_at: null },
    ]);

    await userEvent.click(screen.getByTitle("Отозвать"));

    expect(revoke).toHaveBeenCalledWith("a");
  });

  it("пустой список не выглядит поломкой", () => {
    setup([]);
    expect(screen.getByText("Пока не подключено ни одного клиента")).toBeInTheDocument();
  });
});


describe("подключения через claude.ai", () => {
  it("показываются отдельно от токенов и отключаются", async () => {
    // До этого отключить подключённый claude.ai было нельзя ВООБЩЕ:
    // в настройках лежали только личные токены.
    const { revokeConn } = setup([], undefined, [
      { client_id: "c1", client_name: "Claude", connected_at: "2026-09-10T10:00:00Z", last_refreshed_at: null },
    ]);

    expect(screen.getByText("Подключено через Claude")).toBeInTheDocument();
    expect(screen.getByText("Claude")).toBeInTheDocument();

    await userEvent.click(screen.getByTitle("Отключить"));
    expect(revokeConn).toHaveBeenCalledWith("c1");
  });

  it("блок не показывается, когда подключений нет", () => {
    setup();
    expect(screen.queryByText("Подключено через Claude")).not.toBeInTheDocument();
  });
});

describe("инструкция", () => {
  it("объясняет оба способа и что токен для claude.ai не нужен", async () => {
    // Люди пробуют вставить токен в claude.ai и не понимают, почему он
    // не подходит: там свой поток входа.
    setup();
    await userEvent.click(screen.getByText("Как подключить — по шагам"));

    expect(screen.getByText(/Claude Code \(в терминале\)/)).toBeInTheDocument();
    expect(screen.getByText(/claude.ai \(веб и приложение\)/)).toBeInTheDocument();
    expect(screen.getByText(/Токен для этого не нужен/)).toBeInTheDocument();
  });
});


describe("журнал действий", () => {
  it("показывает событие человеческими словами", async () => {
    // Машинное «mcp.tool» человеку ничего не говорит.
    setup([], undefined, [], [
      { event: "mcp.tool", subject: "search_base", created_at: "2026-09-10T12:00:00Z" },
    ]);

    await userEvent.click(screen.getByText("Что делали с базой"));

    expect(screen.getByText(/Вызов инструмента/)).toBeInTheDocument();
    expect(screen.getByText(/search_base/)).toBeInTheDocument();
  });

  it("обещает, что содержимого заметок там нет", async () => {
    setup();
    await userEvent.click(screen.getByText("Что делали с базой"));
    expect(screen.getByText(/Содержимое заметок сюда не пишется/)).toBeInTheDocument();
  });

  it("пустой журнал не выглядит поломкой", async () => {
    setup();
    await userEvent.click(screen.getByText("Что делали с базой"));
    expect(screen.getByText("Пока ничего не происходило")).toBeInTheDocument();
  });

  it("неизвестное событие показывается как есть, а не пропадает", async () => {
    // Иначе новое событие в бэкенде молча исчезало бы из журнала.
    setup([], undefined, [], [
      { event: "нечто.новое", subject: "", created_at: "2026-09-10T12:00:00Z" },
    ]);
    await userEvent.click(screen.getByText("Что делали с базой"));
    expect(screen.getByText("нечто.новое")).toBeInTheDocument();
  });
});

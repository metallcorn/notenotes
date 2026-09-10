import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import McpSettings from "./McpSettings";

const hooks = vi.hoisted(() => ({
  useMcpTokens: vi.fn(),
  useCreateMcpToken: vi.fn(),
  useRevokeMcpToken: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

function setup(tokens: unknown[] = [], created = { token: "nn_секрет123", id: "t1", name: "" }) {
  const mutateAsync = vi.fn().mockResolvedValue(created);
  const revoke = vi.fn();
  hooks.useMcpTokens.mockReturnValue({ data: tokens, isLoading: false });
  hooks.useCreateMcpToken.mockReturnValue({ mutateAsync, isPending: false });
  hooks.useRevokeMcpToken.mockReturnValue({ mutate: revoke, isPending: false });
  render(<McpSettings />);
  return { mutateAsync, revoke };
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

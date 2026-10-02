import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OfflineFlushNotice from "./OfflineFlushNotice";

const hooks = vi.hoisted(() => ({ useOfflineFlush: vi.fn() }));
vi.mock("../lib/useOfflineFlush", () => hooks);

beforeEach(() => vi.clearAllMocks());

describe("что стало с офлайн-правками", () => {
  it("молчит, когда отправлять было нечего", () => {
    hooks.useOfflineFlush.mockReturnValue([]);
    render(<OfflineFlushNotice />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("говорит, сколько ушло", () => {
    hooks.useOfflineFlush.mockReturnValue([
      { itemId: "a", status: "saved" },
      { itemId: "b", status: "saved" },
    ]);
    render(<OfflineFlushNotice />);
    expect(screen.getByRole("status")).toHaveTextContent("Отправлено правок, сделанных без сети: 2");
  });

  it("объясняет конфликт и что ничего не затёрто", () => {
    // Конфликт здесь не ошибка, а решение: вместо затирания сохранили
    // копию. Умолчать — значит сделать копию сюрпризом, а человека
    // уверенным, что правка применилась.
    hooks.useOfflineFlush.mockReturnValue([
      { itemId: "a", status: "conflict", copyTitle: "Квартира (офлайн-правка)" },
    ]);
    render(<OfflineFlushNotice />);

    const text = screen.getByRole("status").textContent ?? "";
    expect(text).toContain("Квартира");
    expect(text).toContain("сохранена рядом");
    expect(text).toContain("не затереть");
  });

  it("не врёт про успех, если отправить не вышло", () => {
    hooks.useOfflineFlush.mockReturnValue([{ itemId: "a", status: "failed" }]);
    render(<OfflineFlushNotice />);
    expect(screen.getByRole("status")).toHaveTextContent("Не удалось отправить: 1");
  });

  it("закрывается по кнопке", async () => {
    hooks.useOfflineFlush.mockReturnValue([{ itemId: "a", status: "saved" }]);
    render(<OfflineFlushNotice />);

    await userEvent.click(screen.getByLabelText("Скрыть"));

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

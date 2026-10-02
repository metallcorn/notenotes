import { render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OfflineBanner from "./OfflineBanner";

function setOnline(value: boolean) {
  Object.defineProperty(navigator, "onLine", { value, configurable: true });
}

beforeEach(() => setOnline(true));
afterEach(() => vi.restoreAllMocks());

describe("полоска «нет сети»", () => {
  it("не мешает, когда сеть есть", () => {
    render(<OfflineBanner />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("появляется без сети и объясняет цену", () => {
    // Офлайн приложение показывает последнее сохранённое. Без
    // предупреждения человек не отличит его от свежего — и не поймёт,
    // почему правки «не дошли».
    setOnline(false);
    render(<OfflineBanner />);
    expect(screen.getByRole("status")).toHaveTextContent(/Нет сети — показано сохранённое/);
    expect(screen.getByRole("status")).toHaveTextContent(/когда связь вернётся/);
  });

  it("реагирует на обрыв и возврат связи без перезагрузки", () => {
    render(<OfflineBanner />);

    act(() => {
      setOnline(false);
      window.dispatchEvent(new Event("offline"));
    });
    expect(screen.getByRole("status")).toBeInTheDocument();

    act(() => {
      setOnline(true);
      window.dispatchEvent(new Event("online"));
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

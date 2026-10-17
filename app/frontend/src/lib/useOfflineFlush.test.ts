import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Счётчик офлайн-правок. На 17.10 шаг 1 работал пятнадцать дней без единой
// конфликтной копии — но правка без конфликта выглядит как обычное
// сохранение и следа не оставляет. Решение о шаге 2 зависит от этих чисел.

const mocks = vi.hoisted(() => ({
  diagnosticLog: vi.fn(),
  flushQueue: vi.fn(),
  readQueue: vi.fn(),
}));

vi.mock("./diagnostics", () => ({ diagnosticLog: mocks.diagnosticLog }));
vi.mock("./offlineQueue", () => ({ flushQueue: mocks.flushQueue, readQueue: mocks.readQueue }));
vi.mock("../api/client", () => ({ api: { get: vi.fn(), patch: vi.fn(), post: vi.fn() } }));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ invalidateQueries: vi.fn() }) }));

import { useOfflineFlush } from "./useOfflineFlush";

beforeEach(() => {
  // Сбрасывать ВСЕ моки: история вызовов иначе переезжает между тестами,
  // и «не вызывался» во втором тесте видит вызовы из первого.
  mocks.diagnosticLog.mockReset();
  mocks.flushQueue.mockReset();
  mocks.readQueue.mockReset();
  mocks.readQueue.mockResolvedValue([{ itemId: "a" }]);
  Object.defineProperty(navigator, "onLine", { value: true, configurable: true });
});

describe("счётчик офлайн-отправок", () => {
  it("сообщает, сколько дошло, сколько ушло копией и сколько не дошло", async () => {
    mocks.flushQueue.mockResolvedValue([
      { itemId: "a", status: "saved" },
      { itemId: "b", status: "saved" },
      { itemId: "c", status: "conflict", copyTitle: "x" },
      { itemId: "d", status: "failed" },
    ]);

    renderHook(() => useOfflineFlush());

    await waitFor(() => expect(mocks.diagnosticLog).toHaveBeenCalled());
    expect(mocks.diagnosticLog).toHaveBeenCalledWith("offline_flush", { saved: 2, conflict: 1, failed: 1 });
  });

  it("пустая очередь — ничего не отправляет и не пишет", async () => {
    mocks.readQueue.mockResolvedValue([]);

    renderHook(() => useOfflineFlush());

    await new Promise((r) => setTimeout(r, 20));
    expect(mocks.flushQueue).not.toHaveBeenCalled();
    expect(mocks.diagnosticLog).not.toHaveBeenCalled();
  });
});

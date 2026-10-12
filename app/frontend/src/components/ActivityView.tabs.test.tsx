import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Жалоба владельца 12.10: «перехожу на недавние вкладку, а анимации
// перехода скольжения слева направо и наоборот нет».
//
// Проверяем не саму анимацию (её рисует CSS), а два условия, без которых
// она не сработает: правильный класс направления и НОВЫЙ узел при смене
// вкладки — без key React переиспользует элемент, и CSS-анимация не
// переигрывается.

const hooks = vi.hoisted(() => ({
  useAllNotifications: vi.fn(),
  useDetectedEvents: vi.fn(),
  useRecentItems: vi.fn(),
  useDialogs: vi.fn(),
  useSpaces: vi.fn(),
  useDeleteNotification: vi.fn(),
  useDismissDetectedEvent: vi.fn(),
  useMarkNotificationRead: vi.fn(),
  useResolveNotification: vi.fn(),
  useUnresolveNotification: vi.fn(),
}));

vi.mock("../api/hooks", () => hooks);

import ActivityView from "./ActivityView";

const idle = { mutate: vi.fn(), isPending: false };

beforeEach(() => {
  hooks.useAllNotifications.mockReturnValue({ data: [], isLoading: false });
  hooks.useDetectedEvents.mockReturnValue({ data: [], isLoading: false });
  hooks.useRecentItems.mockReturnValue({ data: [], isLoading: false });
  hooks.useDialogs.mockReturnValue({ data: [], isLoading: false });
  hooks.useSpaces.mockReturnValue({ data: [] });
  for (const key of [
    "useDeleteNotification", "useDismissDetectedEvent", "useMarkNotificationRead",
    "useResolveNotification", "useUnresolveNotification",
  ] as const) {
    hooks[key].mockReturnValue(idle);
  }
});

function view() {
  return render(
    <ActivityView onBack={() => {}} onOpenReminder={() => {}} onOpenItem={() => {}} onOpenDialog={() => {}} />,
  );
}

describe("переключение вкладок Активности", () => {
  it("вперёд приезжает справа, назад — слева", async () => {
    const { container } = view();
    const panel = () => container.querySelector("[class*='tab-slide']");

    expect(panel()?.className).toContain("tab-slide-back");

    await userEvent.click(screen.getByRole("button", { name: /Недавнее/ }));
    expect(panel()?.className).toContain("tab-slide-forward");

    await userEvent.click(screen.getByRole("button", { name: /Уведомления/ }));
    expect(panel()?.className).toContain("tab-slide-back");
  });

  it("при смене вкладки узел пересоздаётся", async () => {
    const { container } = view();
    const before = container.querySelector("[class*='tab-slide']");

    await userEvent.click(screen.getByRole("button", { name: /Недавнее/ }));

    const after = container.querySelector("[class*='tab-slide']");
    expect(after).not.toBe(before);
  });

  it("пока список грузится — скелет, а не спиннер", () => {
    hooks.useAllNotifications.mockReturnValue({ data: undefined, isLoading: true });
    const { container } = view();

    expect(container.querySelectorAll(".skeleton").length).toBeGreaterThan(0);
    expect(container.querySelector(".animate-spin")).toBeNull();
  });
});

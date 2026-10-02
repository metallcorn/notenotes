import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ReminderModal from "./ReminderModal";

// Повторяющиеся напоминания: форма должна уметь завести повтор и, что
// важнее, НЕ заводить его молча — случайно включённый повтор человек потом
// идёт отключать каждый день.
describe("ReminderModal: повтор", () => {
  it("по умолчанию повтора нет", async () => {
    const onCreate = vi.fn();
    render(<ReminderModal defaultTitle="Полить цветы" onCreate={onCreate} onCancel={() => {}} />);

    const when = document.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    await userEvent.type(when, "2026-11-10T09:00");
    await userEvent.click(screen.getByRole("button", { name: "Создать" }));

    expect(onCreate).toHaveBeenCalledTimes(1);
    expect(onCreate.mock.calls[0][0].repeat).toBe("");
  });

  it("выбранный период уходит наружу", async () => {
    const onCreate = vi.fn();
    render(<ReminderModal defaultTitle="Оплатить ZUS" onCreate={onCreate} onCancel={() => {}} />);

    const when = document.querySelector('input[type="datetime-local"]') as HTMLInputElement;
    await userEvent.type(when, "2026-11-10T09:00");
    await userEvent.selectOptions(screen.getByRole("combobox"), "monthly");
    await userEvent.click(screen.getByRole("button", { name: "Создать" }));

    expect(onCreate.mock.calls[0][0].repeat).toBe("monthly");
  });

  it("предупреждает, что это будет приходить снова", async () => {
    render(<ReminderModal defaultTitle="x" onCreate={() => {}} onCancel={() => {}} />);

    expect(screen.queryByText(/пока его не удалить/)).toBeNull();
    await userEvent.selectOptions(screen.getByRole("combobox"), "weekly");

    expect(screen.getByText(/каждую неделю, пока его не удалить/)).toBeTruthy();
  });

  it("без времени ничего не создаётся — повтор это не отменяет", async () => {
    const onCreate = vi.fn();
    render(<ReminderModal defaultTitle="x" onCreate={onCreate} onCancel={() => {}} />);

    await userEvent.selectOptions(screen.getByRole("combobox"), "daily");

    expect(screen.getByRole("button", { name: "Создать" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Создать" }));
    expect(onCreate).not.toHaveBeenCalled();
  });
});

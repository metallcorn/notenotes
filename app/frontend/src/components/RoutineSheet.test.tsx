import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RoutineSheet from "./RoutineSheet";
import type { Space } from "../api/types";

// Бытовые дела (04.11): «раз в 30 дней, по субботам» — в режиме «по
// интервалу» выбираются дни недели, и они уходят в расписание вместе с
// временем дня; без дней расписание остаётся прежним.
const hooks = vi.hoisted(() => ({
  useMe: vi.fn(),
  useSpaceMembers: vi.fn(),
  useCreateRoutine: vi.fn(),
  useUpdateRoutine: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

const space: Space = { id: "s1", name: "Dom", owner_id: "u1", created_at: "", icon: null, is_vault: false, is_public_pages: false };

function setup() {
  const mutateAsync = vi.fn().mockResolvedValue({ id: "r1" });
  hooks.useMe.mockReturnValue({ data: { id: "u1" } });
  hooks.useSpaceMembers.mockReturnValue({ data: [] });
  hooks.useCreateRoutine.mockReturnValue({ mutateAsync, isPending: false });
  hooks.useUpdateRoutine.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
  render(<RoutineSheet space={space} onSaved={() => {}} onClose={() => {}} />);
  return mutateAsync;
}

async function switchToInterval() {
  await userEvent.type(screen.getByPlaceholderText(/Название/), "Фильтр поилки");
  await userEvent.click(screen.getByRole("button", { name: "По интервалу" }));
}

describe("RoutineSheet: дни недели", () => {
  beforeEach(() => vi.clearAllMocks());

  it("по субботам раз в 30 дней — дни и время уходят в расписание", async () => {
    const mutateAsync = setup();
    await switchToInterval();
    await userEvent.selectOptions(screen.getByRole("combobox", { name: /Каждые/ }), String(30 * 1440));
    await userEvent.click(screen.getByRole("button", { name: "сб" }));

    expect(screen.getByText(/ближайшего из этих дней/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Создать рутину" }));

    const schedule = mutateAsync.mock.calls[0][0].schedule;
    expect(schedule).toMatchObject({ mode: "interval", every_minutes: 30 * 1440, weekdays: [5], first_at: "10:00" });
  });

  it("без выбранных дней — любой день, weekdays пустой", async () => {
    const mutateAsync = setup();
    await switchToInterval();

    expect(screen.getByText("в любой день")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Создать рутину" }));

    expect(mutateAsync.mock.calls[0][0].schedule.weekdays).toEqual([]);
  });

  it("повторный тап снимает день", async () => {
    const mutateAsync = setup();
    await switchToInterval();
    await userEvent.click(screen.getByRole("button", { name: "сб" }));
    await userEvent.click(screen.getByRole("button", { name: "вс" }));
    await userEvent.click(screen.getByRole("button", { name: "сб" }));
    await userEvent.click(screen.getByRole("button", { name: "Создать рутину" }));

    expect(mutateAsync.mock.calls[0][0].schedule.weekdays).toEqual([6]);
  });
});

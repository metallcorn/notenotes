import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DigestSettings from "./DigestSettings";

const hooks = vi.hoisted(() => ({ useMe: vi.fn(), useUpdateDigestTime: vi.fn() }));
vi.mock("../api/hooks", () => hooks);

function setup(digest_time: string | null) {
  const mutate = vi.fn();
  hooks.useMe.mockReturnValue({ data: { digest_time } });
  hooks.useUpdateDigestTime.mockReturnValue({ mutate, isPending: false });
  render(<DigestSettings />);
  return { mutate };
}

beforeEach(() => vi.clearAllMocks());

describe("утренняя сводка", () => {
  it("выключение шлёт пустую строку, а не null", async () => {
    // null в теле значит «не трогать» — выключение передаётся именно "".
    const { mutate } = setup("09:00");
    await userEvent.click(screen.getByRole("switch"));
    expect(mutate).toHaveBeenCalledWith("");
  });

  it("включение возвращает прежнее или 09:00", async () => {
    const { mutate } = setup(null);
    await userEvent.click(screen.getByRole("switch"));
    expect(mutate).toHaveBeenCalledWith("09:00");
  });

  it("поле времени недоступно, пока выключено", () => {
    setup(null);
    expect(screen.getByDisplayValue("09:00")).toBeDisabled();
  });

  it("объясняет, что пустая сводка не приходит", () => {
    // Иначе человек, у которого утром тихо, решит, что сломалось.
    setup("09:00");
    expect(screen.getByText(/ничего нет, не приходит/)).toBeInTheDocument();
  });
});

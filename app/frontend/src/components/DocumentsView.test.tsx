import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Запрос владельца: «возможно отсортировать или пересобрать отдельно
// где-то все документы, потому что всё сейчас так раскидано». Это ВИД:
// ничего не перемещается, доступы не меняются.

const hooks = vi.hoisted(() => ({ useDocuments: vi.fn() }));
vi.mock("../api/hooks", () => hooks);

import DocumentsView from "./DocumentsView";

const SERIES = {
  key: "ZUS DRA {}.pdf",
  title: "ZUS DRA",
  monthly: true,
  status: "ожидается",
  instalments: [
    { period: "июль 2026", upload_id: "u1", filename: "ZUS DRA 07-2026.pdf", space_name: "Почта", received_on: "2026-08-19" },
    { period: "август 2026", upload_id: "u2", filename: "ZUS DRA 08-2026.pdf", space_name: "Личное", received_on: "2026-09-02" },
  ],
  gaps: [],
  expected_next: "сентябрь 2026",
  expected_by: "2026-10-10",
};

const DOC = {
  id: "d1",
  filename: "karta_pobytu.pdf",
  content_type: "application/pdf",
  size_bytes: 2_200_000,
  created_at: "2026-09-25",
  space_id: "s1",
  space_name: "Личное",
  item_id: "n1",
  item_title: "Документы для ВНЖ",
};

beforeEach(() => {
  hooks.useDocuments.mockReturnValue({ data: { series: [SERIES], documents: [DOC] }, isLoading: false });
});

function view(onOpenItem = vi.fn()) {
  render(<DocumentsView onBack={() => {}} onOpenItem={onOpenItem} />);
  return onOpenItem;
}

describe("вид «Документы»", () => {
  it("серия видна одной линией", () => {
    view();

    expect(screen.getByText("ZUS DRA")).toBeTruthy();
    expect(screen.getByText("июль 2026")).toBeTruthy();
    expect(screen.getByText("август 2026")).toBeTruthy();
  });

  it("состояние серии подписано словами, а не кодом", () => {
    view();

    expect(screen.getByText("ожидается")).toBeTruthy();
    expect(screen.getByText(/обычно приходит к 2026-10-10/)).toBeTruthy();
  });

  it("пропуск в серии показан отдельно", () => {
    hooks.useDocuments.mockReturnValue({
      data: { series: [{ ...SERIES, gaps: ["июль 2026"], status: "задерживается" }], documents: [] },
      isLoading: false,
    });
    view();

    expect(screen.getByText("июль 2026 — нет")).toBeTruthy();
    expect(screen.getByText("задерживается")).toBeTruthy();
  });

  it("из документа можно попасть в заметку, где он лежит", async () => {
    const onOpenItem = view();

    await userEvent.click(screen.getByRole("button", { name: "Документы для ВНЖ" }));

    expect(onOpenItem).toHaveBeenCalledWith("s1", "n1");
  });

  it("поиск фильтрует по имени, спейсу и заметке", async () => {
    view();
    const input = screen.getByPlaceholderText(/Ищет и по тексту/);

    await userEvent.type(input, "ВНЖ");
    expect(screen.getByText("karta_pobytu.pdf")).toBeTruthy();

    await userEvent.clear(input);
    await userEvent.type(input, "ничего такого");
    expect(screen.getByText("Ничего не нашлось")).toBeTruthy();
  });

  it("пока грузится — скелет", () => {
    hooks.useDocuments.mockReturnValue({ data: undefined, isLoading: true });
    const { container } = render(<DocumentsView onBack={() => {}} onOpenItem={() => {}} />);

    expect(container.querySelectorAll(".skeleton").length).toBeGreaterThan(0);
  });

  it("пустая база говорит об этом прямо", () => {
    hooks.useDocuments.mockReturnValue({ data: { series: [], documents: [] }, isLoading: false });
    view();

    expect(screen.getByText("Документов пока нет")).toBeTruthy();
  });
});

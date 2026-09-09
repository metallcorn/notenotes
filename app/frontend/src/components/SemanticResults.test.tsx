import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SemanticResults from "./SemanticResults";
import type { Item, SemanticHit } from "../api/types";

const hooks = vi.hoisted(() => ({ useSemanticSearch: vi.fn() }));
vi.mock("../api/hooks", () => hooks);

function item(id: string, title: string): Item {
  return {
    id,
    space_id: "space-1",
    folder_id: null,
    title,
    content: "",
    material_type: "note",
    properties: {},
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-01T00:00:00Z",
  } as unknown as Item;
}

function hit(id: string, title: string, excerpt: string, score = 0.8): SemanticHit {
  return { item: item(id, title), score, excerpt };
}

function show(data: SemanticHit[] | undefined, state: Partial<{ isLoading: boolean; isError: boolean }> = {}) {
  hooks.useSemanticSearch.mockReturnValue({ isLoading: false, isError: false, data, ...state });
  const onSelect = vi.fn();
  render(<SemanticResults query="ремонт машины" selectedId={null} onSelect={onSelect} excludeIds={[]} />);
  return { onSelect };
}

beforeEach(() => vi.clearAllMocks());

describe("когда блока быть не должно", () => {
  it("ничего не рисует, если смысловых совпадений нет", () => {
    // Порог намеренно строгий (диапазоны осмысленных и посторонних запросов
    // перекрываются, см. routers/search.py) — пустой ответ здесь нормальный
    // исход. Заголовок над пустотой читался бы как поломка.
    show([]);
    expect(screen.queryByText("Похожие по смыслу")).not.toBeInTheDocument();
  });

  it("ничего не рисует при ошибке запроса", () => {
    // Смысловой поиск — необязательное дополнение к уже показанной быстрой
    // выдаче. Его падение не должно портить экран поиска.
    show(undefined, { isError: true });
    expect(screen.queryByText("Похожие по смыслу")).not.toBeInTheDocument();
  });

  it("ничего не рисует, если всё найденное уже есть в быстрой выдаче", () => {
    hooks.useSemanticSearch.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [hit("n1", "Обслуживание", "замена масла")],
    });
    render(
      <SemanticResults query="ремонт" selectedId={null} onSelect={vi.fn()} excludeIds={["n1"]} />,
    );
    expect(screen.queryByText("Похожие по смыслу")).not.toBeInTheDocument();
  });
});

describe("когда есть что показать", () => {
  it("показывает заголовок и совпавший КУСОК, а не начало заметки", () => {
    // Без куска результат по документу на 80 тысяч знаков бесполезен:
    // непонятно, что именно в нём нашлось.
    show([hit("n1", "Техосмотр PJA 34420", "проверка уровня технических жидкостей и фильтров")]);

    expect(screen.getByText("Похожие по смыслу")).toBeInTheDocument();
    expect(screen.getByText("Техосмотр PJA 34420")).toBeInTheDocument();
    expect(screen.getByText(/проверка уровня технических жидкостей/)).toBeInTheDocument();
  });

  it("не повторяет то, что уже показано в быстрой выдаче", () => {
    hooks.useSemanticSearch.mockReturnValue({
      isLoading: false,
      isError: false,
      data: [hit("n1", "Уже показана", "текст"), hit("n2", "Только по смыслу", "другой текст")],
    });
    render(
      <SemanticResults query="ремонт" selectedId={null} onSelect={vi.fn()} excludeIds={["n1"]} />,
    );

    expect(screen.queryByText("Уже показана")).not.toBeInTheDocument();
    expect(screen.getByText("Только по смыслу")).toBeInTheDocument();
  });

  it("заметка без названия не показывается пустой строкой", () => {
    show([hit("n1", "", "текст из середины заметки")]);
    expect(screen.getByText("Без названия")).toBeInTheDocument();
  });

  it("клик открывает заметку", async () => {
    const { onSelect } = show([hit("n1", "Обслуживание", "замена масла")]);
    await userEvent.click(screen.getByRole("button", { name: /Обслуживание/ }));
    expect(onSelect).toHaveBeenCalledWith("n1");
  });
});

describe("пока идёт загрузка", () => {
  it("блок виден сразу, с индикатором", () => {
    // Заявить о себе надо немедленно: иначе человек решит, что ничего не
    // нашлось, и уйдёт раньше, чем придёт ответ.
    show(undefined, { isLoading: true });
    expect(screen.getByText("Похожие по смыслу")).toBeInTheDocument();
  });
});

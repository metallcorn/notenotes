import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import NoteLinkCard from "./NoteLinkCard";
import type { NodeViewProps } from "@tiptap/react";

function makeProps(attrs: { itemId: string | null; title: string }, onOpen = vi.fn()): NodeViewProps {
  return {
    node: { attrs },
    extension: { options: { onOpen } },
  } as unknown as NodeViewProps;
}

describe("NoteLinkCard", () => {
  it("показывает название заметки", () => {
    render(<NoteLinkCard {...makeProps({ itemId: "id-1", title: "Рецепт борща" })} />);
    expect(screen.getByText("Рецепт борща")).toBeInTheDocument();
  });

  it("без названия — запасной текст «Заметка»", () => {
    render(<NoteLinkCard {...makeProps({ itemId: "id-1", title: "" })} />);
    expect(screen.getByText("Заметка")).toBeInTheDocument();
  });

  it("клик вызывает onOpen с itemId (переход внутри приложения)", async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(<NoteLinkCard {...makeProps({ itemId: "id-42", title: "Т" }, onOpen)} />);

    await user.click(screen.getByText("Т"));
    expect(onOpen).toHaveBeenCalledWith("id-42");
  });
});

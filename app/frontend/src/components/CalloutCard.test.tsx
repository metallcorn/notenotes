import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import CalloutCard from "./CalloutCard";
import type { NodeViewProps } from "@tiptap/react";

function makeProps(attrs: { variant: string; title: string | null; open: boolean }, updateAttributes = vi.fn()): NodeViewProps {
  return { node: { attrs }, updateAttributes } as unknown as NodeViewProps;
}

describe("CalloutCard", () => {
  it("спойлер: показывает поле заголовка и кнопку сворачивания, не фиксированную подпись", () => {
    render(<CalloutCard {...makeProps({ variant: "spoiler", title: "Мои детали", open: true })} />);
    expect(screen.getByPlaceholderText("Заголовок спойлера")).toHaveValue("Мои детали");
    expect(screen.getByTitle("Свернуть")).toBeInTheDocument();
  });

  it("info/hint/warning/danger: фиксированная подпись, без поля ввода заголовка", () => {
    render(<CalloutCard {...makeProps({ variant: "warning", title: null, open: true })} />);
    expect(screen.getByText("Важно")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Заголовок спойлера")).not.toBeInTheDocument();
  });

  it("правка заголовка спойлера вызывает updateAttributes", async () => {
    const updateAttributes = vi.fn();
    const user = userEvent.setup();
    render(<CalloutCard {...makeProps({ variant: "spoiler", title: "", open: true }, updateAttributes)} />);

    await user.type(screen.getByPlaceholderText("Заголовок спойлера"), "X");
    expect(updateAttributes).toHaveBeenCalledWith({ title: "X" });
  });

  it("клик по кнопке сворачивания переключает open", async () => {
    const updateAttributes = vi.fn();
    const user = userEvent.setup();
    render(<CalloutCard {...makeProps({ variant: "spoiler", title: "T", open: true }, updateAttributes)} />);

    await user.click(screen.getByTitle("Свернуть"));
    expect(updateAttributes).toHaveBeenCalledWith({ open: false });
  });

  it("закрытый спойлер (open:false) показывает кнопку «Развернуть»", () => {
    render(<CalloutCard {...makeProps({ variant: "spoiler", title: "T", open: false })} />);
    expect(screen.getByTitle("Развернуть")).toBeInTheDocument();
  });
});

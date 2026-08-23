import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import CalloutMenu from "./CalloutMenu";
import type { Editor } from "@tiptap/core";

function makeEditor() {
  const run = vi.fn();
  const insertContent = vi.fn(() => ({ run }));
  const focus = vi.fn(() => ({ insertContent }));
  const chain = vi.fn(() => ({ focus }));
  return { editor: { chain } as unknown as Editor, insertContent, run };
}

describe("CalloutMenu", () => {
  it("открывает список всех пяти вариантов", async () => {
    const { editor } = makeEditor();
    const user = userEvent.setup();
    render(<CalloutMenu editor={editor} />);

    await user.click(screen.getByTitle("Спойлер / плашка"));

    expect(screen.getByText("Спойлер")).toBeInTheDocument();
    expect(screen.getByText("Совет")).toBeInTheDocument();
    expect(screen.getByText("Информация")).toBeInTheDocument();
    expect(screen.getByText("Важно")).toBeInTheDocument();
    expect(screen.getByText("Опасно")).toBeInTheDocument();
  });

  it("клик по «Совет» вставляет callout с variant=hint", async () => {
    const { editor, insertContent } = makeEditor();
    const user = userEvent.setup();
    render(<CalloutMenu editor={editor} />);

    await user.click(screen.getByTitle("Спойлер / плашка"));
    await user.click(screen.getByText("Совет"));

    expect(insertContent).toHaveBeenCalledWith({
      type: "callout",
      attrs: { variant: "hint" },
      content: [{ type: "paragraph" }],
    });
  });

  it("клик по «Спойлер» вставляет callout с open:true", async () => {
    const { editor, insertContent } = makeEditor();
    const user = userEvent.setup();
    render(<CalloutMenu editor={editor} />);

    await user.click(screen.getByTitle("Спойлер / плашка"));
    await user.click(screen.getByText("Спойлер"));

    expect(insertContent).toHaveBeenCalledWith({
      type: "callout",
      attrs: { variant: "spoiler", open: true },
      content: [{ type: "paragraph" }],
    });
  });
});

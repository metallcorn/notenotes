import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import VideoToolbar from "./VideoToolbar";
import type { Editor } from "@tiptap/core";

function makeEditor(attrs: { width?: string | null } = {}) {
  const run = vi.fn();
  const updateAttributes = vi.fn(() => ({ run }));
  const focus = vi.fn(() => ({ updateAttributes }));
  const chain = vi.fn(() => ({ focus }));
  const getAttributes = vi.fn(() => ({ ...attrs }));
  return { editor: { chain, getAttributes } as unknown as Editor, updateAttributes };
}

describe("VideoToolbar", () => {
  it("клик по «Средняя» ставит width 50%", async () => {
    const { editor, updateAttributes } = makeEditor({ width: null });
    const user = userEvent.setup();

    render(<VideoToolbar editor={editor} />);
    await user.click(screen.getByText("Средняя"));

    expect(updateAttributes).toHaveBeenCalledWith("video", { width: "50%" });
  });

  it("повторный клик по уже активной ширине сбрасывает в null (Оригинал)", async () => {
    const { editor, updateAttributes } = makeEditor({ width: "50%" });
    const user = userEvent.setup();

    render(<VideoToolbar editor={editor} />);
    await user.click(screen.getByText("Средняя"));

    expect(updateAttributes).toHaveBeenCalledWith("video", { width: null });
  });

  it("клик по «Оригинал» тоже ставит width null", async () => {
    const { editor, updateAttributes } = makeEditor({ width: "75%" });
    const user = userEvent.setup();

    render(<VideoToolbar editor={editor} />);
    await user.click(screen.getByText("Оригинал"));

    expect(updateAttributes).toHaveBeenCalledWith("video", { width: null });
  });
});

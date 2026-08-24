import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ImageToolbar from "./ImageToolbar";
import type { Editor } from "@tiptap/core";

const hooks = vi.hoisted(() => ({ useReprocessUpload: vi.fn() }));
vi.mock("../api/hooks", () => hooks);

function makeEditor(attrs: { src?: string; rotation?: number } = {}) {
  const run = vi.fn();
  const updateAttributes = vi.fn(() => ({ run }));
  const focus = vi.fn(() => ({ updateAttributes }));
  const chain = vi.fn(() => ({ focus }));
  const getAttributes = vi.fn(() => ({ src: "/api/uploads/abc", ...attrs }));
  return { editor: { chain, getAttributes, state: { selection: { to: 0 } } } as unknown as Editor, updateAttributes };
}

describe("ImageToolbar — поворот", () => {
  it("клик по «Повернуть» на rotation=0 переключает на 90", async () => {
    hooks.useReprocessUpload.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    const { editor, updateAttributes } = makeEditor({ rotation: 0 });
    const user = userEvent.setup();

    render(<ImageToolbar editor={editor} />);
    await user.click(screen.getByText("Повернуть"));

    expect(updateAttributes).toHaveBeenCalledWith("image", { rotation: 90 });
  });

  it("цикл 90 -> 180 -> 270 -> 0", async () => {
    hooks.useReprocessUpload.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    const user = userEvent.setup();

    for (const [from, to] of [[90, 180], [180, 270], [270, 0]] as const) {
      const { editor, updateAttributes } = makeEditor({ rotation: from });
      const { unmount } = render(<ImageToolbar editor={editor} />);
      await user.click(screen.getByText("Повернуть"));
      expect(updateAttributes).toHaveBeenCalledWith("image", { rotation: to });
      unmount();
    }
  });

  it("отсутствие rotation (undefined, старые заметки без атрибута) считается за 0", async () => {
    hooks.useReprocessUpload.mockReturnValue({ mutateAsync: vi.fn(), isPending: false });
    const { editor, updateAttributes } = makeEditor({});
    const user = userEvent.setup();

    render(<ImageToolbar editor={editor} />);
    await user.click(screen.getByText("Повернуть"));

    expect(updateAttributes).toHaveBeenCalledWith("image", { rotation: 90 });
  });
});

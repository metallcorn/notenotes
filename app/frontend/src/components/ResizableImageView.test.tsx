import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ResizableImageView from "./ResizableImageView";
import type { NodeViewProps } from "@tiptap/react";

function makeEditor() {
  return {
    on: vi.fn(),
    off: vi.fn(),
    state: { doc: { textContent: "" } },
  };
}

function makeProps(attrs: {
  src: string;
  width?: string | null;
  align?: string | null;
  rotation?: number;
}): NodeViewProps {
  return { node: { attrs }, editor: makeEditor() } as unknown as NodeViewProps;
}

// Реальный найденный регресс: первая версия поворота (rotation=90/270)
// целиком игнорировала width/align в wrapper'е — кнопки размера/
// выравнивания в ImageToolbar продолжали дёргать setAttrs, но визуально
// ничего не менялось, пока картинка повёрнута. width/align теперь
// применяются всегда, независимо от rotation.
describe("ResizableImageView — width/align работают вместе с поворотом", () => {
  it("width применяется к wrapper при rotation=0", () => {
    render(<ResizableImageView {...makeProps({ src: "/api/uploads/x", width: "50%" })} />);
    expect(screen.getByRole("presentation").parentElement).toHaveStyle({ width: "50%" });
  });

  it("width ПРОДОЛЖАЕТ применяться при rotation=90 (регресс)", () => {
    render(<ResizableImageView {...makeProps({ src: "/api/uploads/x", width: "50%", rotation: 90 })} />);
    expect(screen.getByRole("presentation").parentElement).toHaveStyle({ width: "50%" });
  });

  it("align=center ПРОДОЛЖАЕТ применяться при rotation=270 (регресс)", () => {
    render(<ResizableImageView {...makeProps({ src: "/api/uploads/x", align: "center", rotation: 270 })} />);
    expect(screen.getByRole("presentation").parentElement).toHaveStyle({ marginLeft: "auto", marginRight: "auto" });
  });

  it("rotation по-прежнему применяется как transform на <img>", () => {
    render(<ResizableImageView {...makeProps({ src: "/api/uploads/x", rotation: 90 })} />);
    expect(screen.getByRole("presentation")).toHaveStyle({ transform: "rotate(90deg)" });
  });
});

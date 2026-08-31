import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import VideoView from "./VideoView";
import type { NodeViewProps } from "@tiptap/react";

function makeProps(attrs: { src: string; width?: string | null; size?: number | null }): NodeViewProps {
  return { node: { attrs } } as unknown as NodeViewProps;
}

describe("VideoView", () => {
  it(
    "реальная просьба: оверлей с весом файла виден до воспроизведения и " +
      "гаснет, как только видео запустили",
    () => {
      render(<VideoView {...makeProps({ src: "/api/uploads/x", size: 3 * 1024 * 1024 })} />);

      expect(screen.getByText("3 МБ")).toBeInTheDocument();

      fireEvent.play(document.querySelector("video")!);
      expect(screen.queryByText("3 МБ")).not.toBeInTheDocument();

      fireEvent.pause(document.querySelector("video")!);
      expect(screen.getByText("3 МБ")).toBeInTheDocument();
    },
  );

  it("без известного размера (старые заметки без атрибута) — оверлея нет", () => {
    render(<VideoView {...makeProps({ src: "/api/uploads/x", size: null })} />);
    expect(document.querySelector(".absolute")).not.toBeInTheDocument();
  });

  it("width — реальная просьба: применяется как у картинки", () => {
    render(<VideoView {...makeProps({ src: "/api/uploads/x", width: "50%" })} />);
    const wrapper = document.querySelector("video")!.parentElement as HTMLElement;
    expect(wrapper.style.width).toBe("50%");
  });

  it("без width — во всю доступную ширину (100%)", () => {
    render(<VideoView {...makeProps({ src: "/api/uploads/x" })} />);
    const wrapper = document.querySelector("video")!.parentElement as HTMLElement;
    expect(wrapper.style.width).toBe("100%");
  });
});

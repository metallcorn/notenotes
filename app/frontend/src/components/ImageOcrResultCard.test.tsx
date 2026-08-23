import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ImageOcrResultCard from "./ImageOcrResultCard";
import type { NodeViewProps } from "@tiptap/react";

const hooks = vi.hoisted(() => ({
  useReprocessUpload: vi.fn(),
  useUpdateUploadTranscript: vi.fn(),
}));

vi.mock("../api/hooks", () => hooks);

function mockMutation() {
  return { mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false };
}

function makeProps(attrs: { text: string; uploadId: string | null; canReprocess: boolean }): NodeViewProps {
  return { node: { attrs } } as unknown as NodeViewProps;
}

describe("ImageOcrResultCard", () => {
  it("без uploadId (старые заметки, без миграции) не показывает ни редактирование, ни распознать заново", () => {
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(mockMutation());

    render(<ImageOcrResultCard {...makeProps({ text: "текст", uploadId: null, canReprocess: false })} />);

    expect(screen.queryByTitle("Исправить текст вручную")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Распознать заново")).not.toBeInTheDocument();
  });

  it("с uploadId, но canReprocess=false (голосовая запись) показывает только правку, не «распознать заново»", () => {
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(mockMutation());

    render(<ImageOcrResultCard {...makeProps({ text: "текст", uploadId: "u1", canReprocess: false })} />);

    expect(screen.getByTitle("Исправить текст вручную")).toBeInTheDocument();
    expect(screen.queryByTitle("Распознать заново")).not.toBeInTheDocument();
  });

  it("с canReprocess=true показывает обе кнопки", () => {
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(mockMutation());

    render(<ImageOcrResultCard {...makeProps({ text: "текст", uploadId: "u1", canReprocess: true })} />);

    expect(screen.getByTitle("Исправить текст вручную")).toBeInTheDocument();
    expect(screen.getByTitle("Распознать заново")).toBeInTheDocument();
  });

  it("правка: открывает textarea с текущим текстом и сохраняет через useUpdateUploadTranscript", async () => {
    const updateMutation = mockMutation();
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(updateMutation);

    const user = userEvent.setup();
    render(<ImageOcrResultCard {...makeProps({ text: "Data: 16.01.2014", uploadId: "u1", canReprocess: true })} />);

    await user.click(screen.getByTitle("Исправить текст вручную"));
    const textarea = screen.getByDisplayValue("Data: 16.01.2014");
    await user.clear(textarea);
    await user.type(textarea, "Data: 16.01.2024");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    expect(updateMutation.mutateAsync).toHaveBeenCalledWith({ uploadId: "u1", text: "Data: 16.01.2024" });
  });

  it("распознать заново спрашивает подтверждение и вызывает useReprocessUpload", async () => {
    const reprocessMutation = mockMutation();
    hooks.useReprocessUpload.mockReturnValue(reprocessMutation);
    hooks.useUpdateUploadTranscript.mockReturnValue(mockMutation());
    vi.spyOn(window, "confirm").mockReturnValue(true);

    const user = userEvent.setup();
    render(<ImageOcrResultCard {...makeProps({ text: "текст", uploadId: "u1", canReprocess: true })} />);

    await user.click(screen.getByTitle("Распознать заново"));
    expect(reprocessMutation.mutateAsync).toHaveBeenCalledWith("u1");
  });
});

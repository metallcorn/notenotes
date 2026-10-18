import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ImageOcrResultCard from "./ImageOcrResultCard";
import type { NodeViewProps } from "@tiptap/react";

const hooks = vi.hoisted(() => ({
  useReprocessUpload: vi.fn(),
  useUpdateUploadTranscript: vi.fn(),
}));

vi.mock("../api/hooks", () => hooks);

const client = vi.hoisted(() => ({ api: { get: vi.fn() } }));
vi.mock("../api/client", () => client);

function renderCard(ui: ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

function mockMutation() {
  return { mutate: vi.fn(), mutateAsync: vi.fn().mockResolvedValue(undefined), isPending: false, isError: false };
}

function makeProps(
  attrs: { text: string; uploadId: string | null; canReprocess: boolean },
  updateAttributes = vi.fn(),
): NodeViewProps {
  return { node: { attrs }, updateAttributes } as unknown as NodeViewProps;
}

describe("ImageOcrResultCard", () => {
  it("без uploadId (старые заметки, без миграции) не показывает ни редактирование, ни распознать заново", () => {
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(mockMutation());

    renderCard(<ImageOcrResultCard {...makeProps({ text: "текст", uploadId: null, canReprocess: false })} />);

    expect(screen.queryByTitle("Исправить текст вручную")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Распознать заново")).not.toBeInTheDocument();
  });

  it("с uploadId, но canReprocess=false (голосовая запись) показывает только правку, не «распознать заново»", () => {
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(mockMutation());

    renderCard(<ImageOcrResultCard {...makeProps({ text: "текст", uploadId: "u1", canReprocess: false })} />);

    expect(screen.getByTitle("Исправить текст вручную")).toBeInTheDocument();
    expect(screen.queryByTitle("Распознать заново")).not.toBeInTheDocument();
  });

  it("с canReprocess=true показывает обе кнопки", () => {
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(mockMutation());

    renderCard(<ImageOcrResultCard {...makeProps({ text: "текст", uploadId: "u1", canReprocess: true })} />);

    expect(screen.getByTitle("Исправить текст вручную")).toBeInTheDocument();
    expect(screen.getByTitle("Распознать заново")).toBeInTheDocument();
  });

  it("правка: открывает textarea с текущим текстом и сохраняет через useUpdateUploadTranscript", async () => {
    const updateMutation = mockMutation();
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(updateMutation);

    const user = userEvent.setup();
    renderCard(<ImageOcrResultCard {...makeProps({ text: "Data: 16.01.2014", uploadId: "u1", canReprocess: true })} />);

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
    renderCard(<ImageOcrResultCard {...makeProps({ text: "текст", uploadId: "u1", canReprocess: true })} />);

    await user.click(screen.getByTitle("Распознать заново"));
    expect(reprocessMutation.mutateAsync).toHaveBeenCalledWith("u1");
  });

  // С 18.10 текст живёт в загрузке, а не в заметке (lib/attachmentText.ts).
  it("без текста в узле берёт его из загрузки", async () => {
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(mockMutation());
    client.api.get.mockResolvedValue({ text: "Текст из загрузки", status: "done" });

    const user = userEvent.setup();
    renderCard(<ImageOcrResultCard {...makeProps({ text: "", uploadId: "u9", canReprocess: true })} />);

    await waitFor(() => expect(screen.getByText("Показать распознанный текст")).toBeInTheDocument());
    expect(client.api.get).toHaveBeenCalledWith("/uploads/u9/text");
    await user.click(screen.getByText("Показать распознанный текст"));
    expect((await screen.findAllByText("Текст из загрузки")).length).toBeGreaterThan(0);
  });

  it("после правки блока старого формата убирает из узла его копию текста", async () => {
    hooks.useReprocessUpload.mockReturnValue(mockMutation());
    hooks.useUpdateUploadTranscript.mockReturnValue(mockMutation());
    const updateAttributes = vi.fn();

    const user = userEvent.setup();
    renderCard(
      <ImageOcrResultCard {...makeProps({ text: "старый", uploadId: "u1", canReprocess: false }, updateAttributes)} />,
    );
    await user.click(screen.getByTitle("Исправить текст вручную"));
    await user.type(screen.getByDisplayValue("старый"), " исправлен");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => expect(updateAttributes).toHaveBeenCalledWith({ text: "" }));
  });
});

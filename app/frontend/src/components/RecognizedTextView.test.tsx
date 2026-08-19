import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ReadFullscreenButton } from "./RecognizedTextView";

describe("ReadFullscreenButton", () => {
  // getAllByText, не getByText: RecognizedTextCopyButtons внутри ридера
  // рендерит ещё и СКРЫТЫЙ (className="hidden") ReactMarkdown — источник
  // HTML для форматированной копии в буфер — с тем же текстом, так что
  // после открытия в DOM закономерно два совпадения, не одно.
  it("opens a fullscreen reader with the text on click, closes on X", async () => {
    const user = userEvent.setup();
    render(<ReadFullscreenButton text={"# Заголовок\n\nАбзац с распознанным текстом."} />);

    expect(screen.queryAllByText("Заголовок")).toHaveLength(0);

    await user.click(screen.getByTitle("Читать целиком"));
    expect(screen.getAllByText("Заголовок").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Абзац с распознанным текстом.").length).toBeGreaterThan(0);

    await user.click(screen.getByTitle("Закрыть (Esc)"));
    expect(screen.queryAllByText("Заголовок")).toHaveLength(0);
  });

  it("closes on Escape key", async () => {
    const user = userEvent.setup();
    render(<ReadFullscreenButton text={"Простой текст без заголовков."} />);

    await user.click(screen.getByTitle("Читать целиком"));
    expect(screen.getAllByText("Простой текст без заголовков.").length).toBeGreaterThan(0);

    await user.keyboard("{Escape}");
    expect(screen.queryAllByText("Простой текст без заголовков.")).toHaveLength(0);
  });
});

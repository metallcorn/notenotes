import { describe, expect, it, vi } from "vitest";
import { findTextPosition, scrollToText } from "./findInDoc";

// Жалоба владельца 12.10: «не могу кликнуть на ссылку заметки и перейти к
// тому месту, где эта дата». Напоминание открывало заметку целиком — а это
// 12 554 символа распознанной сервисной книжки.

function editorWith(chunks: { text: string; at: number }[]) {
  return {
    state: {
      doc: {
        descendants(fn: (node: { isText: boolean; text: string }, pos: number) => void) {
          for (const c of chunks) fn({ isText: true, text: c.text }, c.at);
        },
      },
    },
    view: {
      // Node, а не конкретный элемент: domAtPos отдаёт и текстовые узлы,
      // и элементы — на этом сборка и поймала типизацию теста.
      domAtPos: vi.fn((): { node: Node } => ({ node: document.createElement("span") })),
    },
  };
}

describe("поиск места в заметке", () => {
  it("находит позицию с учётом смещения узла", () => {
    const editor = editorWith([
      { text: "HISTORIA SERWISOWA", at: 1 },
      { text: "do 73 000 km lub do dnia 10.12.2026", at: 100 },
    ]);

    expect(findTextPosition(editor, "10.12.2026")).toBe(100 + "do 73 000 km lub do dnia ".length);
  });

  it("берёт первое вхождение", () => {
    const editor = editorWith([
      { text: "срок 10.12.2026 первый", at: 10 },
      { text: "и снова 10.12.2026", at: 200 },
    ]);

    expect(findTextPosition(editor, "10.12.2026")).toBe(15);
  });

  it("нет текста — нет позиции", () => {
    const editor = editorWith([{ text: "ничего похожего", at: 1 }]);

    expect(findTextPosition(editor, "10.12.2026")).toBeNull();
  });

  it("пустой запрос не ищем", () => {
    const editor = editorWith([{ text: "любой текст", at: 1 }]);

    expect(findTextPosition(editor, "   ")).toBeNull();
  });

  it("не нашлось — scrollToText честно говорит false", () => {
    const editor = editorWith([{ text: "нет такой даты", at: 1 }]);

    expect(scrollToText(editor, "10.12.2026")).toBe(false);
  });

  it("нашлось — прокручивает и подсвечивает тем же классом, что якорь", () => {
    const element = document.createElement("span");
    element.scrollIntoView = vi.fn();
    const editor = editorWith([{ text: "до 10.12.2026", at: 1 }]);
    editor.view.domAtPos = vi.fn(() => ({ node: element }));

    vi.useFakeTimers();
    expect(scrollToText(editor, "10.12.2026")).toBe(true);
    expect(element.scrollIntoView).toHaveBeenCalled();
    expect(element.classList.contains("reminder-anchor-highlight")).toBe(true);

    // Подсветка снимается сама — иначе заметка осталась бы жёлтой навсегда.
    vi.advanceTimersByTime(2600);
    expect(element.classList.contains("reminder-anchor-highlight")).toBe(false);
    vi.useRealTimers();
  });

  it("текстовый узел поднимается до элемента", () => {
    const parent = document.createElement("p");
    const textNode = document.createTextNode("до 10.12.2026");
    parent.appendChild(textNode);
    parent.scrollIntoView = vi.fn();
    const editor = editorWith([{ text: "до 10.12.2026", at: 1 }]);
    editor.view.domAtPos = vi.fn(() => ({ node: textNode }));

    expect(scrollToText(editor, "10.12.2026")).toBe(true);
    expect(parent.scrollIntoView).toHaveBeenCalled();
  });
});

describe("вторая стратегия: прокрутка к вложению", () => {
  // Срок документа находится не только в тексте заметки, но и в
  // РАСПОЗНАННОМ ТЕКСТЕ ФАЙЛА — он хранится на загрузке, а не внутри
  // заметки. Живой случай 12.10: «Техосмотр Citroën», дата 11.03.2027
  // есть в transcript фотографии и отсутствует в content заметки.
  function editorWithDom(dom: HTMLElement) {
    return {
      state: { doc: { descendants: () => {} } },
      view: { domAtPos: vi.fn((): { node: Node } => ({ node: dom })), dom },
    };
  }

  const UPLOAD = "a9c5661d-e386-44d6-942b-bd3b6a5684d9";

  it("находит картинку по id загрузки", () => {
    const root = document.createElement("div");
    const img = document.createElement("img");
    img.setAttribute("src", `/api/uploads/${UPLOAD}`);
    img.scrollIntoView = vi.fn();
    root.appendChild(img);

    expect(scrollToText(editorWithDom(root), UPLOAD)).toBe(true);
    expect(img.scrollIntoView).toHaveBeenCalled();
  });

  it("находит блок документа по data-url", () => {
    const root = document.createElement("div");
    const block = document.createElement("div");
    block.setAttribute("data-url", `/api/uploads/${UPLOAD}`);
    block.scrollIntoView = vi.fn();
    root.appendChild(block);

    expect(scrollToText(editorWithDom(root), UPLOAD)).toBe(true);
  });

  it("нет ни текста, ни вложения — false, и заметка просто открыта", () => {
    const root = document.createElement("div");

    expect(scrollToText(editorWithDom(root), UPLOAD)).toBe(false);
  });
});

describe("устойчивость селектора вложений", () => {
  // Найдено ревью 17.10: селектор держался на src и data-url, а карточка
  // документа рисуется через ReactNodeViewRenderer — атрибуты из
  // renderHTML приходят пропсом и на узел не попадают. Для .docx-вложения
  // без превью не находилось ничего.
  function editorWithDom(dom: HTMLElement) {
    return {
      state: { doc: { descendants: () => {} } },
      view: { domAtPos: vi.fn((): { node: Node } => ({ node: dom })), dom },
    };
  }

  const UPLOAD = "34560123-42a6-440f-8663-db90e963f853";

  it("находит карточку документа по href", () => {
    const root = document.createElement("div");
    const link = document.createElement("a");
    link.setAttribute("href", `/api/uploads/${UPLOAD}`);
    link.scrollIntoView = vi.fn();
    root.appendChild(link);

    expect(scrollToText(editorWithDom(root), UPLOAD)).toBe(true);
    expect(link.scrollIntoView).toHaveBeenCalled();
  });

  it("находит карточку распознанного текста по data-upload-id", () => {
    const root = document.createElement("div");
    const card = document.createElement("div");
    card.setAttribute("data-upload-id", UPLOAD);
    card.scrollIntoView = vi.fn();
    root.appendChild(card);

    expect(scrollToText(editorWithDom(root), UPLOAD)).toBe(true);
  });

  it("кривое значение из URL не роняет экран", () => {
    // Значение приходит из адреса; кавычка в нём уронила бы querySelector
    // исключением, а React пересбросил бы его на ErrorBoundary — человек
    // вместо «не прокрутилось» получил бы развалившуюся заметку.
    const root = document.createElement("div");

    expect(() => scrollToText(editorWithDom(root), '"]')).not.toThrow();
    expect(scrollToText(editorWithDom(root), '"]')).toBe(false);
  });
});

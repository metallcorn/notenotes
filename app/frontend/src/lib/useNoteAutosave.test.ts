import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AUTOSAVE_DEBOUNCE_MS, useNoteAutosave } from "./useNoteAutosave";

/**
 * Тот самый тест, ради которого автосохранение вынесено из NoteEditor.
 *
 * Через Playwright гонку воспроизвести не удалось за восемь заходов (разбор
 * в докстринге pendingSave.ts): снаружи браузера нужное состояние не
 * собирается — «несохранённое» для второй заметки просто не возникало, и
 * тест оставался зелёным даже с намеренно сломанной защитой. Здесь
 * переходы состояния задаются напрямую, поэтому воспроизводится ровно то,
 * что случилось у пользователя.
 *
 * ПРОВЕРЕНО, ЧТО ТЕСТ ЛОВИТ БАГ. С обеими снятыми защитами (состояние кода
 * ДО починки) два теста ниже падают, и падают буквально с содержимым
 * инцидента:
 *
 *   "content": "",                      "id": "B"   ← пустота в заметку B
 *   "content": "текст ПЕРВОЙ заметки",  "id": "B"   ← чужой текст под её id
 *
 * Важная деталь для того, кто будет это трогать: защит ДВЕ, и каждой по
 * отдельности достаточно — снять одну и ждать красноты бесполезно, тест
 * останется зелёным. Первая (здесь, в useNoteAutosave) не даёт очереди
 * заполниться для недогруженной заметки, вторая (shouldFlushPendingSave)
 * не даёт записать уже накопленное. Так и задумано: досохранение работает
 * без дебаунса, и одного рубежа для потери данных мало.
 */

type Args = Parameters<typeof useNoteAutosave>[0];

function setup(overrides: Partial<Args> = {}) {
  const save = vi.fn();
  const title = (overrides.title as string) ?? "Первая";
  const content = (overrides.content as string) ?? "текст первой";
  // savedRef согласован с начальным состоянием ДО первого рендера — как в
  // жизни после загрузки заметки. Иначе хук справедливо считает первый же
  // рендер несохранённой правкой, и все проверки ниже ловили бы её, а не
  // то, ради чего написаны (на этом тест и упал в первый раз).
  const savedRef = { current: { title, content } };
  const base: Args = {
    itemId: "A",
    item: { id: "A" },
    title: "Первая",
    content: "текст первой",
    initializedItemId: "A",
    updateAvailable: false,
    savedRef,
    save,
    onStatus: vi.fn(),
    ...overrides,
  };
  const view = renderHook((props: Args) => useNoteAutosave(props), { initialProps: base });
  return { view, save, savedRef, base };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("обычная работа", () => {
  it("сохраняет правку после паузы", () => {
    const { view, save, base } = setup();

    view.rerender({ ...base, content: "текст первой и добавка" });
    expect(save).not.toHaveBeenCalled(); // ещё не время

    act(() => void vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    expect(save).toHaveBeenCalledWith({ id: "A", title: "Первая", content: "текст первой и добавка" });
  });

  it("не сохраняет, если ничего не менялось", () => {
    const { view, save, base } = setup();

    view.rerender({ ...base });
    act(() => void vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    expect(save).not.toHaveBeenCalled();
  });

  it("досохраняет незавершённую правку при уходе с заметки", () => {
    // Ради этого досохранение и работает мгновенно: иначе правка, сделанная
    // за миг до переключения, терялась бы.
    const { view, save, base } = setup();

    view.rerender({ ...base, content: "успел дописать" });
    act(() => view.rerender({ ...base, itemId: "B", item: { id: "B" }, initializedItemId: "A" }));

    expect(save).toHaveBeenCalledWith({ id: "A", title: "Первая", content: "успел дописать" });
  });
});

describe("потеря данных 2026-09-08", () => {
  it("НЕ записывает пустоту в заметку, которая не успела догрузиться", () => {
    // Ровно то, что случилось: открыл заметку, через 567 мс ушёл, а
    // документ ещё догружался — и досохранение отправило пустоту, обнулив
    // заметку на 2228 символов.
    const { view, save, base } = setup();

    // Переключились на B. Её содержимое ещё не в редакторе: initializedItemId
    // всё ещё указывает на A, а content — переходное, пустое.
    act(() =>
      view.rerender({
        ...base,
        itemId: "B",
        item: { id: "B" },
        initializedItemId: "A",
        title: "Вторая",
        content: "",
      }),
    );
    // Ушли с B раньше, чем она догрузилась.
    act(() => view.unmount());

    expect(save).not.toHaveBeenCalled();
  });

  it("не приписывает состояние одной заметки другой", () => {
    // Вторая форма той же ошибки: id уже новый, а содержимое ещё старое.
    // Записать так — значит затереть B текстом из A.
    const { view, save, base } = setup();

    act(() =>
      view.rerender({
        ...base,
        itemId: "B",
        item: { id: "B" },
        initializedItemId: "A",
        content: "текст ПЕРВОЙ заметки",
      }),
    );
    act(() => view.unmount());

    expect(save).not.toHaveBeenCalled();
  });

  it("сохраняет как обычно, когда заметка догрузилась", () => {
    // Обратная сторона: защита не должна глушить настоящие правки в B.
    const { view, save, base } = setup();

    view.rerender({
      ...base,
      itemId: "B",
      item: { id: "B" },
      initializedItemId: "B",
      title: "Вторая",
      content: "правка во второй",
    });
    act(() => void vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));

    expect(save).toHaveBeenCalledWith({ id: "B", title: "Вторая", content: "правка во второй" });
  });
});

describe("обновление приложения", () => {
  it("не пишет на сервер, пока висит баннер обновления", () => {
    // Схема могла измениться — запись старым клиентом опаснее, чем
    // потерянная правка (баннер прямо просит перезагрузиться).
    const { view, save, base } = setup({ updateAvailable: true });

    view.rerender({ ...base, updateAvailable: true, content: "правка" });
    act(() => void vi.advanceTimersByTime(AUTOSAVE_DEBOUNCE_MS));
    act(() => view.unmount());

    expect(save).not.toHaveBeenCalled();
  });
});

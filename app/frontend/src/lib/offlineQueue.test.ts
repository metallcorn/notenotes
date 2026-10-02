import { beforeEach, describe, expect, it, vi } from "vitest";
import { dropFromQueue, enqueueEdit, flushQueue, readQueue, type QueuedEdit } from "./offlineQueue";

/**
 * Очередь офлайн-правок. Главное правило, ради которого всё это и
 * написано: ТЕКСТ НЕ ТЕРЯЕТСЯ — ни при конфликте, ни при повторном
 * обрыве, ни если заметку удалили.
 *
 * Слияния здесь нет намеренно (это шаг 2): 19.08 «тихое» сохранение
 * устаревшей вкладкой трижды затёрло свежий текст. Конфликт разрешается
 * копией рядом, а не перезаписью.
 */

const store = new Map<string, unknown>();
vi.mock("idb-keyval", () => ({
  get: async (k: string) => store.get(k),
  set: async (k: string, v: unknown) => void store.set(k, v),
  del: async (k: string) => void store.delete(k),
}));

function edit(over: Partial<QueuedEdit> = {}): QueuedEdit {
  return {
    itemId: "note-1",
    title: "Квартира",
    content: "замеры, 2252 знака",
    editedAt: Date.parse("2026-10-02T10:00:00Z"),
    baseUpdatedAt: "2026-10-02T09:00:00Z",
    ...over,
  };
}

function deps(over: Partial<Parameters<typeof flushQueue>[0]> = {}) {
  return {
    fetchItem: vi.fn(async () => ({ updated_at: "2026-10-02T09:00:00Z", title: "Квартира", space_id: "s1" })),
    patchItem: vi.fn(async () => {}),
    createCopy: vi.fn(async () => {}),
    ...over,
  };
}

beforeEach(() => store.clear());

describe("накопление", () => {
  it("правка переживает закрытие вкладки", async () => {
    await enqueueEdit(edit());
    expect(await readQueue()).toHaveLength(1);
  });

  it("на заметку — одна запись, а не история", async () => {
    // Несколько правок подряд офлайн — это последнее состояние текста,
    // а не версии.
    await enqueueEdit(edit({ content: "первая" }));
    await enqueueEdit(edit({ content: "вторая" }));

    const queue = await readQueue();
    expect(queue).toHaveLength(1);
    expect(queue[0].content).toBe("вторая");
  });

  it("разные заметки не вытесняют друг друга", async () => {
    await enqueueEdit(edit({ itemId: "a" }));
    await enqueueEdit(edit({ itemId: "b" }));
    expect(await readQueue()).toHaveLength(2);
  });

  it("сломанное хранилище не роняет редактор", async () => {
    const broken = await vi.importActual<typeof import("./offlineQueue")>("./offlineQueue");
    store.set("notenotes-offline-queue", "не массив");
    // readQueue вернёт мусор как есть — важно, что не бросит.
    await expect(broken.readQueue()).resolves.toBeDefined();
  });
});

describe("отправка, когда связь вернулась", () => {
  it("сохраняет, если заметку никто не трогал", async () => {
    await enqueueEdit(edit());
    const d = deps();

    const out = await flushQueue(d);

    expect(out).toEqual([{ itemId: "note-1", status: "saved" }]);
    expect(d.patchItem).toHaveBeenCalledOnce();
    expect(await readQueue()).toHaveLength(0);
  });

  it("НЕ затирает, если заметка изменилась, пока мы были офлайн", async () => {
    // Ровно тот класс, что 19.08 стоил данных: другое устройство,
    // ассистент или бот успели записать своё.
    await enqueueEdit(edit());
    const d = deps({
      fetchItem: vi.fn(async () => ({ updated_at: "2026-10-02T09:30:00Z", title: "Квартира", space_id: "s1" })),
    });

    const out = await flushQueue(d);

    expect(d.patchItem).not.toHaveBeenCalled();
    expect(d.createCopy).toHaveBeenCalledOnce();
    expect(out[0]).toMatchObject({ status: "conflict" });
    expect(out[0]).toHaveProperty("copyTitle", expect.stringContaining("офлайн-правка"));
  });

  it("удалённая заметка не повод выбросить текст", async () => {
    await enqueueEdit(edit());
    const d = deps({ fetchItem: vi.fn(async () => null) });

    const out = await flushQueue(d);

    expect(d.createCopy).toHaveBeenCalledOnce();
    expect(out[0]).toMatchObject({ status: "conflict" });
  });

  it("повторный обрыв ОСТАВЛЯЕТ правку в очереди", async () => {
    // Единственное, чего здесь нельзя, — потерять текст.
    await enqueueEdit(edit());
    const d = deps({ patchItem: vi.fn(async () => { throw new Error("сеть пропала"); }) });

    const out = await flushQueue(d);

    expect(out[0]).toMatchObject({ status: "failed" });
    expect(await readQueue()).toHaveLength(1);
  });

  it("одна упавшая не мешает остальным", async () => {
    await enqueueEdit(edit({ itemId: "a" }));
    await enqueueEdit(edit({ itemId: "b" }));
    const d = deps({
      patchItem: vi.fn(async (e: QueuedEdit) => {
        if (e.itemId === "a") throw new Error("сбой");
      }),
    });

    const out = await flushQueue(d);

    expect(out.map((o) => o.status)).toEqual(["failed", "saved"]);
    expect((await readQueue()).map((q) => q.itemId)).toEqual(["a"]);
  });

  it("без baseUpdatedAt конфликт не выдумываем", async () => {
    // Заметка, про которую мы не знали исходной версии: затирать
    // осознанно, иначе любая правка превращалась бы в копию.
    await enqueueEdit(edit({ baseUpdatedAt: null }));
    const d = deps({
      fetchItem: vi.fn(async () => ({ updated_at: "2026-10-02T23:00:00Z", title: "x", space_id: "s1" })),
    });

    await flushQueue(d);

    expect(d.patchItem).toHaveBeenCalledOnce();
  });

  it("пустая очередь — не работа", async () => {
    const d = deps();
    expect(await flushQueue(d)).toEqual([]);
    expect(d.fetchItem).not.toHaveBeenCalled();
  });
});

describe("снятие с очереди", () => {
  it("убирает только названную заметку", async () => {
    await enqueueEdit(edit({ itemId: "a" }));
    await enqueueEdit(edit({ itemId: "b" }));

    await dropFromQueue("a");

    expect((await readQueue()).map((q) => q.itemId)).toEqual(["b"]);
  });
});

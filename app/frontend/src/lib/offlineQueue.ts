// Очередь правок, сделанных без сети (ТЗ §18, шаг 1 офлайн-редактирования).
//
// Что это решает. Офлайн правка заметки уходила в никуда: PATCH падал,
// react-query с retry: false просто показывал ошибку, и текст жил только в
// памяти вкладки — до закрытия. Теперь он переживает и закрытие, и
// перезагрузку, и уходит на сервер, когда связь вернётся.
//
// ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО — слияния. Это шаг 2, и он опаснее: 19.08
// устаревшая вкладка трижды затёрла свежий текст именно «тихим»
// сохранением. Поэтому здесь правило простое и тупое: если на сервере
// заметка изменилась ПОСЛЕ того, как человек начал править офлайн, мы не
// затираем — мы сохраняем офлайн-версию рядом, отдельной заметкой, и
// говорим об этом. Потерять данные нельзя, слить молча — тоже.
//
// Хранилище — IndexedDB (idb-keyval), как у персиста react-query:
// localStorage мал и синхронен, а здесь лежат целые тексты заметок.
import { get, set } from "idb-keyval";

const QUEUE_KEY = "notenotes-offline-queue";

export type QueuedEdit = {
  itemId: string;
  title: string;
  content: string;
  /** Когда правка сделана — по ним же разрешаем порядок применения. */
  editedAt: number;
  /**
   * updated_at заметки, какой её видел редактор НАЧИНАЯ править. Если на
   * сервере сейчас новее — значит кто-то (другое устройство, ассистент,
   * бот) успел изменить её, пока мы были офлайн, и затирать нельзя.
   */
  baseUpdatedAt: string | null;
};

export async function readQueue(): Promise<QueuedEdit[]> {
  try {
    return (await get<QueuedEdit[]>(QUEUE_KEY)) ?? [];
  } catch {
    // Приватный режим, вычищенное хранилище, квота — офлайн-очередь
    // необязательна, и её поломка не повод ронять редактор.
    return [];
  }
}

async function writeQueue(queue: QueuedEdit[]): Promise<void> {
  try {
    await set(QUEUE_KEY, queue);
  } catch {
    /* см. readQueue */
  }
}

/**
 * Поставить правку в очередь. На одну заметку — одна запись: несколько
 * правок подряд офлайн это не «история», а последнее состояние текста.
 */
export async function enqueueEdit(edit: QueuedEdit): Promise<void> {
  const queue = await readQueue();
  const rest = queue.filter((q) => q.itemId !== edit.itemId);
  await writeQueue([...rest, edit]);
}

export async function dropFromQueue(itemId: string): Promise<void> {
  const queue = await readQueue();
  await writeQueue(queue.filter((q) => q.itemId !== itemId));
}

export type FlushOutcome =
  | { itemId: string; status: "saved" }
  /** Заметку изменили, пока мы были офлайн — офлайн-версия сохранена рядом. */
  | { itemId: string; status: "conflict"; copyTitle: string }
  | { itemId: string; status: "failed" };

type FlushDeps = {
  fetchItem: (id: string) => Promise<{ updated_at: string; title: string; space_id: string } | null>;
  patchItem: (edit: QueuedEdit) => Promise<void>;
  createCopy: (edit: QueuedEdit, title: string, spaceId: string) => Promise<void>;
};

/**
 * Отправить накопленное. Возвращает, что с каждой правкой стало, —
 * вызывающий код решает, что показать человеку.
 *
 * Зависимости передаются снаружи, а не импортируются: это единственное
 * место, где решается судьба офлайн-правки, и оно должно проверяться
 * тестами без сети и без react-query (тот же довод, что у pendingSave.ts).
 */
export async function flushQueue(deps: FlushDeps): Promise<FlushOutcome[]> {
  const queue = await readQueue();
  const results: FlushOutcome[] = [];

  for (const edit of queue) {
    try {
      const current = await deps.fetchItem(edit.itemId);
      if (current === null) {
        // Заметку удалили, пока мы были офлайн. Текст всё равно не теряем.
        await deps.createCopy(edit, `${edit.title || "Без названия"} (офлайн-правка)`, "");
        results.push({ itemId: edit.itemId, status: "conflict", copyTitle: edit.title });
        await dropFromQueue(edit.itemId);
        continue;
      }

      const changedMeanwhile =
        edit.baseUpdatedAt !== null && new Date(current.updated_at) > new Date(edit.baseUpdatedAt);

      if (changedMeanwhile) {
        const copyTitle = `${edit.title || current.title || "Без названия"} (офлайн-правка)`;
        await deps.createCopy(edit, copyTitle, current.space_id);
        results.push({ itemId: edit.itemId, status: "conflict", copyTitle });
      } else {
        await deps.patchItem(edit);
        results.push({ itemId: edit.itemId, status: "saved" });
      }
      await dropFromQueue(edit.itemId);
    } catch {
      // Сеть опять пропала или сервер ответил ошибкой — ОСТАВЛЯЕМ в
      // очереди. Единственное, чего здесь нельзя, — потерять текст.
      results.push({ itemId: edit.itemId, status: "failed" });
    }
  }

  return results;
}

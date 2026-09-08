import { useEffect, useRef } from "react";
import { shouldFlushPendingSave, type PendingSave } from "./pendingSave";

/**
 * Автосохранение заметки: дебаунс на обычные правки плюс немедленное
 * досохранение при уходе с заметки.
 *
 * Вынесено из NoteEditor не ради красоты. Это единственное место, где
 * решается судьба содержимого заметки, — а сам NoteEditor тянет полсотни
 * зависимостей (TipTap, Yjs, десяток хуков API) и юнит-тестами намеренно
 * не покрыт. Здесь та же логика живёт отдельно от редактора, и её можно
 * проверить целиком, включая переходы состояния, а не только правило
 * «писать или не писать» (shouldFlushPendingSave).
 *
 * Реальная потеря данных, ради которой это разделение и сделано
 * (2026-09-08, две заметки; восстановленные из истории версий стёрлись
 * СНОВА). Из логов посекундно:
 *
 *   15:57:07.589  GET   <B>          открыл заметку
 *   15:57:08.156  PATCH <B>          ← запись ПУСТОГО, заметка обнулена
 *   15:57:08.162  GET   <A>          ушёл на другую
 *
 * Пользователь быстро переключался между заметками. Открыл одну, через
 * 567 мс ушёл — и досохранение записало то, что было в редакторе. А там
 * было пусто: документ ещё догружался. Дебаунс в 1200 мс не спасал,
 * досохранение по замыслу срабатывает мгновенно, иначе терялись бы
 * последние правки.
 */
export type NoteAutosaveStatus = "idle" | "saving" | "saved";

export const AUTOSAVE_DEBOUNCE_MS = 1200;

export function useNoteAutosave({
  itemId,
  item,
  title,
  content,
  /** Заметка, для которой загрузка ПОЛНОСТЬЮ завершилась (см. NoteEditor). */
  initializedItemId,
  /** Доступно обновление приложения — писать нельзя, схема могла измениться. */
  updateAvailable,
  /** Базовая точка «это уже на сервере». Мутируется и снаружи, при загрузке. */
  savedRef,
  save,
  onStatus,
}: {
  itemId: string;
  item: { id: string } | undefined;
  title: string;
  content: string;
  initializedItemId: string | null;
  updateAvailable: boolean;
  savedRef: { current: { title: string; content: string } };
  save: (payload: { id: string; title: string; content: string }) => void;
  onStatus: (status: NoteAutosaveStatus) => void;
}): void {
  const pendingRef = useRef<PendingSave>(null);

  // Через ref, а не напрямую: эффекты ниже намеренно не подписаны на эти
  // значения (иначе дебаунс перезапускался бы от каждой смены), но читать
  // должны всегда свежее.
  const latest = useRef({ initializedItemId, updateAvailable, save });
  useEffect(() => {
    latest.current = { initializedItemId, updateAvailable, save };
  });

  useEffect(() => {
    if (!item) return;
    // Заметка ещё не догрузилась — то, что сейчас в редакторе, не её
    // содержимое, а переходное состояние (часто пустое). Именно эта
    // проверка не даёт записать его на сервер.
    if (latest.current.initializedItemId !== item.id) return;
    if (title === savedRef.current.title && content === savedRef.current.content) {
      pendingRef.current = null;
      return;
    }
    pendingRef.current = { id: item.id, title, content };
    onStatus("saving");
    const timer = setTimeout(() => {
      if (latest.current.updateAvailable) return;
      latest.current.save({ id: item.id, title, content });
      savedRef.current = { title, content };
      pendingRef.current = null;
      onStatus("saved");
    }, AUTOSAVE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // Зависимости РОВНО как были в NoteEditor до выноса: [title, content].
    // item.id сюда добавлять нельзя — эффект начал бы перезапускаться при
    // смене заметки и трогать очередь в тот самый момент переключения,
    // ради которого всё и затевалось. Рефакторинг обязан сохранить
    // поведение, а не «улучшить» его заодно.
  }, [title, content]);

  // Ушли с заметки, пока правка не сохранилась — досохраняем немедленно, а
  // не теряем её.
  useEffect(() => {
    return () => {
      const pending = pendingRef.current;
      // Второй рубеж к проверке выше. Досохранение работает БЕЗ дебаунса:
      // если сюда попадёт переходное состояние недогруженной заметки, оно
      // уйдёт на сервер сразу и ничто его не остановит.
      if (shouldFlushPendingSave(pending, latest.current.initializedItemId, latest.current.updateAvailable)) {
        latest.current.save({ id: pending!.id, title: pending!.title, content: pending!.content });
      }
      pendingRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemId]);
}

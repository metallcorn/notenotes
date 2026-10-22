import { useEffect, useRef, useState } from "react";
import { MessageSquareText, Plus, Sparkles, Trash2, X } from "lucide-react";
import { useCreateDialog, useDeleteItem, useScopedDialogs } from "../api/hooks";
import type { DialogSummary } from "../api/types";
import { uiStorage } from "../lib/storage";
import AssistantChat from "./AssistantChat";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";
import { dateLocale } from "../i18n";

function formatDialogDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(dateLocale, { day: "numeric", month: "short" }) + ", " +
    d.toLocaleTimeString(dateLocale, { hour: "2-digit", minute: "2-digit" });
}

const MIN_WIDTH = 320;
const MAX_WIDTH = 800;

// Реальный запрос: "хочу использовать ассистента прямо в заметке — выделил
// текст, он ищет/обогащает, предлагает вставить результат". Полноценный
// ассистент (тулы: web_search/read_website/search_base/get_note), но
// привязанный к этой заметке (scoped_item_id — см. create_dialog в
// routers/dialogs.py) — видит её содержимое без пересказа, тулов изменения
// данных нет вообще (ничего не создаст/не удалит молча), результат
// применяет пользователь кнопкой "Вставить в заметку" на каждом ответе
// (см. onApplyToNote в AssistantChat.tsx). Скретч-чат не показывается в
// общем списке диалогов, но реально сохраняется — при повторном открытии
// показываем список прошлых разговоров об этой заметке (реальный запрос:
// "хочу видеть предыдущие и выбрать, а не только последний"), а не
// создаём молча новый каждый раз.
export default function NoteAssistantModal({
  itemId,
  selectionText,
  onApply,
  onClose,
}: {
  itemId: string;
  selectionText: string | null;
  onApply: (text: string) => void;
  onClose: () => void;
}) {
  const createDialog = useCreateDialog();
  const scopedDialogs = useScopedDialogs();
  const deleteItem = useDeleteItem(undefined);
  const [dialogId, setDialogId] = useState<string | null>(null);
  const [pastDialogs, setPastDialogs] = useState<DialogSummary[] | undefined>(undefined);
  // Реальная жалоба: "как удалять чаты от заметки? надо в этом окне где
  // они предлагаются сделать кнопку удаления" — тот же паттерн, что уже
  // есть у DialogList.tsx (общий список диалогов ассистента).
  const [deletingDialog, setDeletingDialog] = useState<DialogSummary | null>(null);
  const [width, setWidth] = useState(() => uiStorage.getNotePanelWidth());
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia("(min-width: 1024px)").matches);
  const draggingRef = useRef(false);

  function startNewDialog() {
    createDialog.mutateAsync({ scoped_item_id: itemId, selection: selectionText ?? undefined }).then((dialog) => {
      setDialogId(dialog.id);
    });
  }

  useEffect(() => {
    let cancelled = false;
    setDialogId(null);
    setPastDialogs(undefined);
    scopedDialogs
      .mutateAsync(itemId)
      .then((dialogs) => {
        if (cancelled) return;
        if (dialogs.length === 0) {
          // Диалогов ещё не было — выбирать не из чего, сразу новый.
          setPastDialogs([]);
          startNewDialog();
        } else {
          setPastDialogs(dialogs);
        }
      })
      .catch(() => {
        // Не удалось получить список (сеть и т.п.) — не блокируем
        // ассистента из-за этого, просто открываем новый разговор.
        if (cancelled) return;
        setPastDialogs([]);
        startNewDialog();
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itemId]);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const handler = () => setIsDesktop(mq.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Тянем за левый край панели — она сама прижата к правому краю экрана,
  // поэтому новая ширина это расстояние от курсора до правого края окна.
  function onHandlePointerDown(e: React.PointerEvent<HTMLDivElement>) {
    draggingRef.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function onHandlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!draggingRef.current) return;
    const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, window.innerWidth - e.clientX));
    setWidth(next);
    uiStorage.setNotePanelWidth(next);
  }
  function onHandlePointerUp(e: React.PointerEvent<HTMLDivElement>) {
    draggingRef.current = false;
    e.currentTarget.releasePointerCapture(e.pointerId);
  }

  return (
    <>
      {/* Затемнение-фон только на мобиле — реальная жалоба: на десктопе
          модалка по центру перекрывает саму заметку, хотя её как раз
          хочется видеть параллельно с чатом (сверяться, куда вставится
          результат). На узком экране места на "рядом" нет физически, там
          обычная модалка поверх всего — остаётся как было. */}
      <div className="fixed inset-0 z-50 bg-black/40 lg:hidden" onClick={onClose} />
      {/* Телефон: во весь экран (замечание 22.10 — в узкой модалке поле
          ввода оставалось крохотным), планшет — модалка по центру. */}
      <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-0 sm:p-4 lg:items-stretch lg:justify-end lg:p-0">
        <div
          style={isDesktop ? { width } : undefined}
          className="panel-slide-in pointer-events-auto relative flex h-dvh w-full max-w-xl flex-col overflow-hidden bg-surface shadow-xl sm:h-[85vh] sm:rounded-3xl lg:h-full lg:max-w-none lg:rounded-none lg:border-l lg:shadow-2xl"
        >
          {/* Ручка изменения ширины — только на десктопе, на телефоне
              панель на всю ширину, тянуть нечего. */}
          <div
            onPointerDown={onHandlePointerDown}
            onPointerMove={onHandlePointerMove}
            onPointerUp={onHandlePointerUp}
            className="absolute -left-1 top-0 hidden h-full w-2 cursor-col-resize touch-none lg:block"
          />
          {dialogId ? (
            <AssistantChat
              dialogId={dialogId}
              onBack={onClose}
              onOpenItem={() => {}}
              onApplyToNote={onApply}
              contextNote={selectionText ?? undefined}
              alwaysShowBack
            />
          ) : pastDialogs && pastDialogs.length > 0 ? (
            <div className="flex h-full flex-col">
              <div className="flex items-center gap-3 px-3 pt-3 pb-2">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-brand text-white" aria-hidden="true">
                  <Sparkles size={18} strokeWidth={2.4} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[17px] font-extrabold text-primary">Ассистент</div>
                  <div className="truncate text-xs font-semibold text-subtle">по этой заметке</div>
                </div>
                <button
                  onClick={onClose}
                  aria-label="Закрыть"
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-muted text-primary hover:bg-muted-hover"
                >
                  <X size={20} strokeWidth={2.4} />
                </button>
              </div>
              {/* Макет «Ассистент: диалоги»: кнопка нового разговора
                  сверху фиолетовой, прошлые разговоры — карточками. */}
              <div className="flex-1 overflow-y-auto px-3 pb-4">
                <button
                  onClick={startNewDialog}
                  className="flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-brand text-[15px] font-extrabold text-white hover:bg-brand/90"
                >
                  <Plus size={18} strokeWidth={2.6} /> Начать новый разговор
                </button>
                <div className="px-1 pb-1.5 pt-4 text-[11px] font-extrabold uppercase tracking-wider text-subtle">
                  Прошлые разговоры по заметке
                </div>
                <div className="flex flex-col gap-2">
                  {pastDialogs.map((d) => (
                    <div key={d.id} className="flex items-center rounded-2xl bg-muted hover:bg-muted-hover">
                      <button onClick={() => setDialogId(d.id)} className="flex min-h-14 min-w-0 flex-1 items-center gap-3 px-3.5 text-left">
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-text">
                          <MessageSquareText size={16} />
                        </span>
                        <span className="min-w-0 flex-1">
                          {/* Заголовок у всех диалогов этой заметки одинаковый
                              ("Ассистент: {название заметки}") — без превью
                              первого вопроса их не отличить друг от друга. */}
                          <span className="block truncate text-[15px] font-extrabold text-primary">
                            {d.preview || "Новый диалог без сообщений"}
                          </span>
                          <span className="block text-xs font-semibold text-subtle">{formatDialogDate(d.updated_at)}</span>
                        </span>
                      </button>
                      <button
                        onClick={() => setDeletingDialog(d)}
                        title="Удалить диалог"
                        className="mr-1.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-subtle hover:bg-danger-soft hover:text-danger"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="flex h-full flex-col">
              <div className="flex items-center gap-3 px-3 pt-3 pb-2">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-brand text-white" aria-hidden="true">
                  <Sparkles size={18} strokeWidth={2.4} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-[17px] font-extrabold text-primary">Ассистент</div>
                  <div className="truncate text-xs font-semibold text-subtle">по этой заметке</div>
                </div>
                <button
                  onClick={onClose}
                  aria-label="Закрыть"
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-muted text-primary hover:bg-muted-hover"
                >
                  <X size={20} strokeWidth={2.4} />
                </button>
              </div>
              <div className="flex flex-1 items-center justify-center text-subtle">
                <Spinner />
              </div>
            </div>
          )}
        </div>
      </div>
      {deletingDialog && (
        <ConfirmDialog
          title={`Удалить диалог «${deletingDialog.preview || "Новый диалог"}»? Он переместится в корзину.`}
          danger
          onConfirm={async () => {
            const id = deletingDialog.id;
            await deleteItem.mutateAsync(id);
            setDeletingDialog(null);
            setPastDialogs((prev) => {
              const next = (prev ?? []).filter((d) => d.id !== id);
              // Последний диалог заметки удалён — сразу открываем новый,
              // не оставляем пустой тупиковый экран (тот же случай, что
              // выше в useEffect, когда прошлых диалогов не было вообще).
              if (next.length === 0) startNewDialog();
              return next;
            });
          }}
          onCancel={() => setDeletingDialog(null)}
        />
      )}
    </>
  );
}

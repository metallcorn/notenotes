import { useEffect, useRef, useState } from "react";
import { Trash2, X } from "lucide-react";
import { useCreateDialog, useDeleteItem, useScopedDialogs } from "../api/hooks";
import type { DialogSummary } from "../api/types";
import { uiStorage } from "../lib/storage";
import AssistantChat from "./AssistantChat";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";

function formatDialogDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" }) + ", " +
    d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
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
      <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-4 lg:items-stretch lg:justify-end lg:p-0">
        <div
          style={isDesktop ? { width } : undefined}
          className="panel-slide-in pointer-events-auto relative flex h-[85vh] w-full max-w-xl flex-col overflow-hidden rounded-lg bg-surface shadow-xl lg:h-full lg:max-w-none lg:rounded-none lg:border-l lg:shadow-2xl"
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
              <div className="flex items-center justify-between border-b px-3 py-2">
                <span className="text-sm font-medium text-subtle">Ассистент</span>
                <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded text-subtle hover:bg-muted-hover">
                  <X size={16} />
                </button>
              </div>
              <div className="flex-1 overflow-y-auto px-3 py-3">
                <p className="mb-2 text-sm text-secondary">У этой заметки уже есть разговоры с ассистентом:</p>
                <div className="flex flex-col gap-1">
                  {pastDialogs.map((d) => (
                    <div key={d.id} className="flex items-center gap-1 rounded border hover:bg-muted-hover">
                      <button onClick={() => setDialogId(d.id)} className="min-w-0 flex-1 px-3 py-2 text-left text-sm">
                        {/* Заголовок у всех диалогов этой заметки одинаковый
                            ("Ассистент: {название заметки}") — реальная
                            жалоба: без превью первого вопроса их не отличить
                            друг от друга. Показываем превью как основную
                            строку, заголовок — не дублируем вовсе. */}
                        <div className="truncate font-medium text-primary">
                          {d.preview || "Новый диалог без сообщений"}
                        </div>
                        <div className="text-xs text-subtle">{formatDialogDate(d.updated_at)}</div>
                      </button>
                      <button
                        onClick={() => setDeletingDialog(d)}
                        title="Удалить диалог"
                        className="mr-2 flex h-7 w-7 shrink-0 items-center justify-center text-subtle hover:text-danger"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  ))}
                </div>
                <button
                  onClick={startNewDialog}
                  className="mt-3 w-full rounded bg-accent px-3 py-1.5 text-sm text-white hover:bg-accent/90"
                >
                  Начать новый разговор
                </button>
              </div>
            </div>
          ) : (
            <div className="flex h-full flex-col">
              <div className="flex items-center justify-between border-b px-3 py-2">
                <span className="text-sm font-medium text-subtle">Ассистент</span>
                <button onClick={onClose} className="flex h-7 w-7 items-center justify-center rounded text-subtle hover:bg-muted-hover">
                  <X size={16} />
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

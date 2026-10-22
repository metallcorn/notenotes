import { Suspense, lazy, useEffect } from "react";
import { createPortal } from "react-dom";
import type { Item } from "../api/types";
import { useUpdateItem } from "../api/hooks";
import { NOTE_COLORS } from "../lib/noteColors";
import Spinner from "./Spinner";
import { t } from "../i18n";

const EmojiPicker = lazy(() => import("emoji-picker-react"));

// Шторка «Вид заметки» (макет 21.10): сверху — как заметка будет выглядеть
// в списке (значок + цветной заголовок), ниже — пикер эмодзи со своим
// поиском и ряд цветов заголовка. Каждый выбор сохраняется сразу, «Готово»
// просто закрывает.
export default function NoteLookSheet({ item, onClose }: { item: Item; onClose: () => void }) {
  const updateItem = useUpdateItem();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const dark = typeof document !== "undefined" && document.documentElement.classList.contains("dark");

  return createPortal(
    <div
      className="modal-in fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("look.title")}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="sheet-in flex max-h-[90dvh] w-full max-w-md flex-col rounded-t-3xl bg-surface px-4 pb-[max(20px,var(--safe-bottom))] pt-2.5 shadow-xl sm:rounded-3xl sm:pb-5"
      >
        <div className="mx-auto mb-3 h-[5px] w-10 shrink-0 rounded-full bg-muted-active sm:hidden" aria-hidden="true" />
        <div className="flex shrink-0 items-center gap-3.5 rounded-2xl bg-muted p-3.5">
          <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-surface text-4xl leading-none">
            {item.icon ?? "🙂"}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[22px] font-extrabold tracking-tight text-primary" style={item.color ? { color: item.color } : undefined}>
              {item.title || "Без названия"}
            </div>
            <div className="text-[13px] font-semibold text-subtle">{t("look.preview")}</div>
          </div>
        </div>

        <div className="mt-3.5 min-h-0 flex-1 overflow-y-auto">
          <Suspense
            fallback={
              <div className="flex h-40 items-center justify-center">
                <Spinner size={20} />
              </div>
            }
          >
            <EmojiPicker
              onEmojiClick={(data) => updateItem.mutate({ id: item.id, icon: data.emoji })}
              width="100%"
              height={320}
              theme={(dark ? "dark" : "light") as never}
              searchPlaceHolder={t("look.searchEmoji")}
              previewConfig={{ showPreview: false }}
              lazyLoadEmojis
            />
          </Suspense>

          <div className="mt-4 px-1 text-[11px] font-extrabold uppercase tracking-wider text-subtle">{t("look.titleColor")}</div>
          <div className="mt-2 flex flex-wrap items-center gap-2.5 px-1">
            <button
              type="button"
              onClick={() => updateItem.mutate({ id: item.id, color: null })}
              aria-label={t("look.noColor")}
              className={`flex h-10 w-10 items-center justify-center rounded-full border-2 border-strong bg-surface text-sm font-bold text-subtle ${
                !item.color ? "ring-2 ring-primary ring-offset-2 ring-offset-surface" : ""
              }`}
            >
              ×
            </button>
            {NOTE_COLORS.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => updateItem.mutate({ id: item.id, color: c })}
                style={{ backgroundColor: c }}
                aria-label={`Цвет ${c}`}
                className={`h-10 w-10 rounded-full ${item.color === c ? "ring-2 ring-primary ring-offset-2 ring-offset-surface" : ""}`}
              />
            ))}
          </div>
        </div>

        <div className="mt-3.5 flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => updateItem.mutate({ id: item.id, icon: null })}
            disabled={!item.icon}
            className="h-[52px] flex-1 rounded-2xl bg-muted text-[15px] font-bold text-primary disabled:opacity-50"
          >
            {t("look.removeEmoji")}
          </button>
          <button type="button" onClick={onClose} className="h-[52px] flex-1 rounded-2xl bg-accent text-[15px] font-extrabold text-on-accent">
            {t("common.done")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

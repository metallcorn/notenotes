import { useState } from "react";

export default function PromptDialog({
  title,
  initialValue = "",
  confirmLabel = "Сохранить",
  onConfirm,
  onCancel,
}: {
  title: string;
  initialValue?: string;
  confirmLabel?: string;
  onConfirm: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initialValue);

  return (
    // position: fixed, а не absolute — не зависит от overflow ближайшего
    // скроллящегося родителя (см. баг с всплывающими окнами в сайдбаре).
    <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim()) onConfirm(value.trim());
        }}
        className="w-full max-w-sm rounded-3xl bg-surface p-5 shadow-xl"
      >
        <div className="mb-3 text-[15px] font-bold leading-snug text-primary">{title}</div>
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="h-12 w-full rounded-2xl border bg-surface px-4 text-[15px] outline-none focus:ring-2 focus:ring-brand/40"
        />
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="h-11 rounded-2xl px-4 text-sm font-bold text-secondary hover:bg-muted"
          >
            Отмена
          </button>
          <button type="submit" className="h-11 rounded-2xl bg-accent px-4 text-sm font-extrabold text-on-accent">
            {confirmLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (value.trim()) onConfirm(value.trim());
        }}
        className="w-full max-w-sm rounded-lg bg-white p-4 shadow-xl"
      >
        <div className="mb-2 text-sm font-medium text-slate-900">{title}</div>
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="w-full rounded border px-3 py-2 text-sm"
        />
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100"
          >
            Отмена
          </button>
          <button type="submit" className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white">
            {confirmLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

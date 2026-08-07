export default function ConfirmDialog({
  title,
  danger = false,
  confirmLabel = "Удалить",
  onConfirm,
  onCancel,
}: {
  title: string;
  danger?: boolean;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-lg bg-white p-4 shadow-xl">
        <div className="mb-4 text-sm text-slate-900">{title}</div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100">
            Отмена
          </button>
          <button
            onClick={onConfirm}
            className={`rounded px-3 py-1.5 text-sm text-white ${danger ? "bg-red-600 hover:bg-red-700" : "bg-slate-900"}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

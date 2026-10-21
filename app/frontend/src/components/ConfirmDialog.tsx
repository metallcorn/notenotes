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
    <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-3xl bg-surface p-5 shadow-xl">
        <div className="mb-5 text-[15px] font-bold leading-snug text-primary">{title}</div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="h-11 rounded-2xl px-4 text-sm font-bold text-secondary hover:bg-muted">
            Отмена
          </button>
          <button
            onClick={onConfirm}
            className={`h-11 rounded-2xl px-4 text-sm font-extrabold ${
              danger ? "bg-danger-soft text-danger hover:bg-danger/20" : "bg-accent text-on-accent"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

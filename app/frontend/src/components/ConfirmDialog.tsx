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
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-lg bg-surface p-4 shadow-xl">
        <div className="mb-4 text-sm text-primary">{title}</div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded px-3 py-1.5 text-sm text-subtle hover:bg-muted-hover">
            Отмена
          </button>
          <button
            onClick={onConfirm}
            className={`rounded px-3 py-1.5 text-sm text-white ${danger ? "bg-danger hover:bg-danger/90" : "bg-accent"}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

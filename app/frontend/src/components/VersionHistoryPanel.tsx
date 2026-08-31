import { useItemVersions, useRevertVersion } from "../api/hooks";

export default function VersionHistoryPanel({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const { data: versions, isLoading } = useItemVersions(itemId);
  const revert = useRevertVersion(itemId);

  return (
    <aside className="w-72 shrink-0 overflow-y-auto border-l bg-muted p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-subtle">История версий</span>
        <button onClick={onClose} className="text-subtle hover:text-secondary">
          ×
        </button>
      </div>
      {isLoading && <p className="text-sm text-subtle">Загрузка…</p>}
      {!isLoading && (versions ?? []).length === 0 && (
        <p className="text-sm text-subtle">Изменений пока не было</p>
      )}
      <ul className="space-y-2">
        {(versions ?? []).map((v) => (
          <li key={v.id} className="rounded border bg-surface p-2">
            <div className="text-xs text-subtle">{new Date(v.created_at).toLocaleString("ru-RU")}</div>
            <div className="mt-0.5 truncate text-sm font-medium text-primary">{v.title || "Без названия"}</div>
            <div className="mt-0.5 line-clamp-2 text-xs text-subtle">{v.content.slice(0, 140)}</div>
            <button
              onClick={() => {
                if (window.confirm("Восстановить эту версию? Текущее состояние тоже сохранится в истории.")) {
                  revert.mutate(v.id);
                }
              }}
              className="mt-1 text-xs text-subtle underline hover:text-primary"
            >
              Восстановить
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}

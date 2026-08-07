import { useItemVersions, useRevertVersion } from "../api/hooks";

export default function VersionHistoryPanel({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const { data: versions, isLoading } = useItemVersions(itemId);
  const revert = useRevertVersion(itemId);

  return (
    <aside className="w-72 shrink-0 overflow-y-auto border-l bg-slate-50 p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-400">История версий</span>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
          ×
        </button>
      </div>
      {isLoading && <p className="text-sm text-slate-400">Загрузка…</p>}
      {!isLoading && (versions ?? []).length === 0 && (
        <p className="text-sm text-slate-400">Изменений пока не было</p>
      )}
      <ul className="space-y-2">
        {(versions ?? []).map((v) => (
          <li key={v.id} className="rounded border bg-white p-2">
            <div className="text-xs text-slate-400">{new Date(v.created_at).toLocaleString("ru-RU")}</div>
            <div className="mt-0.5 truncate text-sm font-medium text-slate-800">{v.title || "Без названия"}</div>
            <div className="mt-0.5 line-clamp-2 text-xs text-slate-500">{v.content.slice(0, 140)}</div>
            <button
              onClick={() => {
                if (window.confirm("Восстановить эту версию? Текущее состояние тоже сохранится в истории.")) {
                  revert.mutate(v.id);
                }
              }}
              className="mt-1 text-xs text-slate-500 underline hover:text-slate-900"
            >
              Восстановить
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}

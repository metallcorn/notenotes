import { useItemVersions, useRevertVersion } from "../api/hooks";
import { ListSkeleton } from "./Skeleton";
import { dateLocale } from "../i18n";

export default function VersionHistoryPanel({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const { data: versions, isLoading } = useItemVersions(itemId);
  const revert = useRevertVersion(itemId);

  return (
    <aside className="w-72 shrink-0 overflow-y-auto border-l bg-muted p-3">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-[15px] font-extrabold tracking-tight text-primary">История версий</span>
        <button onClick={onClose} aria-label="Закрыть" className="flex h-9 w-9 items-center justify-center rounded-xl bg-surface text-primary shadow-card">
          ×
        </button>
      </div>
      {isLoading && <ListSkeleton rows={4} withIcon={false} />}
      {!isLoading && (versions ?? []).length === 0 && (
        <p className="text-sm text-subtle">Изменений пока не было</p>
      )}
      <ul className="space-y-2">
        {(versions ?? []).map((v) => (
          <li key={v.id} className="rounded-2xl bg-surface p-3 shadow-card">
            <div className="text-[11px] font-bold uppercase tracking-wide text-subtle">{new Date(v.created_at).toLocaleString(dateLocale)}</div>
            <div className="mt-1 truncate text-sm font-extrabold text-primary">{v.title || "Без названия"}</div>
            <div className="mt-0.5 line-clamp-2 text-xs text-subtle">{v.content.slice(0, 140)}</div>
            <button
              onClick={() => {
                if (window.confirm("Восстановить эту версию? Текущее состояние тоже сохранится в истории.")) {
                  revert.mutate(v.id);
                }
              }}
              className="mt-2 h-8 rounded-full bg-muted px-3 text-xs font-bold text-primary hover:bg-muted-hover"
            >
              Вернуть эту версию
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}

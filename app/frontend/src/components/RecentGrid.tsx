import { FileText, ListChecks, Table as TableIcon } from "lucide-react";
import { useItem, useRecentItems } from "../api/hooks";
import type { Item } from "../api/types";
import { listCounts, previewText } from "./NoteList";
import { formatRelativeDay } from "../lib/format";
import { dateLocale, t } from "../i18n";

// «Недавние» на Главной телефона (макет «Главная», 21.10): четыре плитки
// 2×2. Сначала то, что недавно ОТКРЫВАЛИ на этом устройстве
// (uiStorage.recentlyOpened — замечание 22.10: только что прочитанная
// заметка в «Недавние» не попадала), затем — последние изменённые
// (useRecentItems, как вкладка «Недавнее» в Активности).

function Tile({ item, onOpen }: { item: Item; onOpen: (spaceId: string, itemId: string) => void }) {
  const isList = item.material_type === "list";
  const isTable = item.material_type === "table";
  const counts = isList ? listCounts(item.content) : null;
  const preview = isList || isTable ? "" : previewText(item.content);
  return (
    <button
      onClick={() => onOpen(item.space_id, item.id)}
      className="row-fade-in flex min-h-[112px] flex-col rounded-2xl bg-surface p-3.5 text-left shadow-card active:scale-[0.98]"
    >
      <div className="flex items-center gap-1.5 text-[15px] font-extrabold leading-tight text-primary">
        {isList ? (
          <ListChecks size={16} className="shrink-0" />
        ) : isTable ? (
          <TableIcon size={16} className="shrink-0" />
        ) : item.icon ? (
          <span className="text-lg leading-none">{item.icon}</span>
        ) : (
          <FileText size={16} className="shrink-0 text-subtle" />
        )}
        <span className="line-clamp-2" style={item.color ? { color: item.color } : undefined}>
          {item.title || "Без названия"}
        </span>
      </div>
      {preview && <div className="mt-1.5 line-clamp-2 text-[13px] leading-snug text-subtle">{preview}</div>}
      {counts && counts.total > 0 && (
        <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-muted">
          <div className="h-full rounded-full bg-brand" style={{ width: `${Math.round((counts.done / counts.total) * 100)}%` }} />
        </div>
      )}
      <div className="mt-auto pt-2 text-xs font-bold text-nav-muted">
        {counts ? `${counts.done} из ${counts.total} · ` : ""}
        {formatRelativeDay(item.updated_at, dateLocale)}
      </div>
    </button>
  );
}

// Открытая недавно запись: своим запросом (обычно уже в кэше — её только
// что смотрели). Удалённая или недоступная — плитка не рисуется.
function OpenedTile({ id, spaceId, onOpen }: { id: string; spaceId: string | null; onOpen: (spaceId: string, itemId: string) => void }) {
  const { data: item } = useItem(id);
  if (!item || item.deleted_at || (spaceId && item.space_id !== spaceId)) return null;
  return <Tile item={item} onOpen={onOpen} />;
}

export default function RecentGrid({
  spaceId,
  openedIds,
  onOpen,
  onAll,
}: {
  // Пилюли спейсов на Главной: null — все спейсы.
  spaceId: string | null;
  openedIds: string[];
  onOpen: (spaceId: string, itemId: string) => void;
  onAll: () => void;
}) {
  const { data: items } = useRecentItems();
  const opened = openedIds.slice(0, 4);
  const modified = (items ?? [])
    .filter((i) => (!spaceId || i.space_id === spaceId) && !opened.includes(i.id))
    .slice(0, Math.max(0, 4 - opened.length));
  if (opened.length === 0 && modified.length === 0) return null;
  return (
    <section aria-label={t("home.recent")} className="mb-3">
      <div className="mb-2 flex items-baseline justify-between px-1">
        <h2 className="text-lg font-extrabold tracking-tight text-primary">{t("home.recent")}</h2>
        <button onClick={onAll} className="text-sm font-bold text-brand-text">
          {t("home.allNotes")}
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2.5">
        {opened.map((id) => (
          <OpenedTile key={id} id={id} spaceId={spaceId} onOpen={onOpen} />
        ))}
        {modified.map((item) => (
          <Tile key={item.id} item={item} onOpen={onOpen} />
        ))}
      </div>
    </section>
  );
}

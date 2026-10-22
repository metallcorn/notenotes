import { useState } from "react";
import { Copy, X } from "lucide-react";
import { useItem, useItemVersions, useMe, useRevertVersion, useSpaceMembers } from "../api/hooks";
import type { ItemVersion } from "../api/types";
import { collapseUnchanged, diffStats, lineDiff } from "../lib/lineDiff";
import { ListSkeleton } from "./Skeleton";
import { dateLocale, tn } from "../i18n";

// История версий (макет 21.10): сверху — выбранная версия с подсветкой
// того, что в ней поменялось относительно следующей (более новой), кнопки
// «Вернуть эту версию»/«Копия»; ниже — лента всех версий с точками и
// автором. На телефоне — весь экран, на десктопе — боковая панель.
export default function VersionHistoryPanel({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const { data: versions, isLoading } = useItemVersions(itemId);
  const { data: item } = useItem(itemId);
  const { data: me } = useMe();
  const { data: members } = useSpaceMembers(item?.space_id);
  const revert = useRevertVersion(itemId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const list = versions ?? [];
  // Версии приходят новые → старые.
  const selected = list.find((v) => v.id === selectedId) ?? list[0];
  const selectedIndex = selected ? list.indexOf(selected) : -1;
  // Что было ПОСЛЕ этой версии: следующая новее, у самой новой — текущее
  // состояние заметки. Diff показывает, что изменилось при переходе от
  // выбранной версии к более новой.
  const newer: { title: string; content: string } | undefined =
    selectedIndex > 0 ? list[selectedIndex - 1] : item ? { title: item.title, content: item.content } : undefined;
  const diff = selected && newer ? lineDiff(selected.content, newer.content) : [];
  const stats = diffStats(diff);
  const chunks = collapseUnchanged(diff);

  function authorLabel(v: ItemVersion | null): string {
    if (!v || v.author_id === null) return "Ассистент";
    if (me && v.author_id === me.id) return "Ты";
    const m = members?.find((x) => x.user_id === v.author_id);
    return m ? m.name || m.username : "Участник";
  }
  const dotColor = (v: ItemVersion | null) =>
    !v || v.author_id === null ? "bg-brand" : me && v.author_id === me.id ? "bg-primary" : "bg-[#F2A65A]";
  const when = (iso: string) => new Date(iso).toLocaleString(dateLocale, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

  async function copySelected() {
    if (!selected) return;
    try {
      await navigator.clipboard.writeText(selected.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // буфер недоступен — молча
    }
  }

  return (
    <aside className="fixed inset-0 z-40 flex flex-col overflow-y-auto bg-app md:static md:z-auto md:w-80 md:shrink-0 md:border-l">
      <div className="flex items-center gap-2 px-3 pt-3 md:pt-3">
        <button
          onClick={onClose}
          aria-label="Закрыть"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card"
        >
          <X size={20} strokeWidth={2.4} />
        </button>
        <div className="min-w-0">
          <div className="text-lg font-extrabold leading-tight text-primary">История версий</div>
          <div className="truncate text-xs font-semibold text-subtle">
            {item?.title || "Без названия"}
            {list.length > 0 ? ` · ${tn("count.versions", list.length)}` : ""}
          </div>
        </div>
      </div>

      {isLoading && (
        <div className="p-4">
          <ListSkeleton rows={4} withIcon={false} />
        </div>
      )}
      {!isLoading && list.length === 0 && <p className="p-4 text-sm font-semibold text-subtle">Изменений пока не было</p>}

      {selected && (
        <div className="mx-3 mt-4 rounded-3xl bg-surface p-4 shadow-card">
          <div className="flex items-center justify-between gap-2">
            <span className="truncate rounded-full bg-brand-soft px-2.5 py-1 text-xs font-extrabold text-brand-text">
              {authorLabel(selected)} · {when(selected.created_at)}
            </span>
            {newer && (
              <span className="shrink-0 text-xs font-bold text-subtle">
                +{stats.added} −{stats.removed}
              </span>
            )}
          </div>
          {selected.title !== (newer?.title ?? selected.title) && (
            <div className="mt-2 text-sm font-extrabold text-primary">{selected.title || "Без названия"}</div>
          )}
          <div className="mt-3 max-h-64 overflow-y-auto text-[14px] leading-relaxed">
            {diff.length === 0 || (stats.added === 0 && stats.removed === 0) ? (
              <div className="whitespace-pre-wrap text-secondary">{selected.content.slice(0, 600) || "—"}</div>
            ) : (
              chunks.map((c, i) =>
                c.kind === "skip" ? (
                  <div key={i} className="my-1 text-center text-xs font-bold text-subtle">
                    … {tn("count.lines", c.count)} без изменений …
                  </div>
                ) : (
                  <div
                    key={i}
                    className={`-mx-1.5 my-0.5 whitespace-pre-wrap break-words rounded-lg px-1.5 ${
                      c.kind === "add"
                        ? "bg-success-soft text-success"
                        : c.kind === "del"
                          ? "bg-danger-soft text-danger line-through"
                          : "text-secondary"
                    }`}
                  >
                    {c.text || " "}
                  </div>
                ),
              )
            )}
          </div>
          <div className="mt-3.5 flex gap-2">
            <button
              onClick={() => {
                if (window.confirm("Восстановить эту версию? Текущее состояние тоже сохранится в истории.")) {
                  revert.mutate(selected.id);
                }
              }}
              disabled={revert.isPending}
              className="h-[46px] flex-1 rounded-2xl bg-accent text-sm font-extrabold text-on-accent disabled:opacity-50"
            >
              Вернуть эту версию
            </button>
            <button
              onClick={copySelected}
              className="flex h-[46px] items-center gap-1.5 rounded-2xl bg-muted px-3.5 text-sm font-bold text-primary"
            >
              <Copy size={14} /> {copied ? "Готово" : "Копия"}
            </button>
          </div>
        </div>
      )}

      {list.length > 0 && (
        <>
          <div className="px-5 pb-2 pt-4 text-[11px] font-extrabold uppercase tracking-wider text-subtle">Все версии</div>
          <ol className="mx-3 mb-4 space-y-0.5">
            <li className="flex items-center gap-3 px-1.5 py-2.5">
              <span className="h-3 w-3 shrink-0 rounded-full bg-primary" aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="text-sm font-extrabold text-primary">Сейчас</div>
                {item && <div className="text-xs font-semibold text-subtle">{when(item.updated_at)}</div>}
              </div>
            </li>
            {list.map((v) => (
              <li key={v.id}>
                <button
                  onClick={() => setSelectedId(v.id)}
                  className={`flex w-full items-center gap-3 rounded-2xl px-1.5 py-2.5 text-left ${
                    selected?.id === v.id ? "bg-brand-soft" : "hover:bg-muted"
                  }`}
                >
                  <span className={`h-3 w-3 shrink-0 rounded-full ${dotColor(v)}`} aria-hidden="true" />
                  <div className="min-w-0 flex-1">
                    <div className={`truncate text-sm font-extrabold ${selected?.id === v.id ? "text-brand-text" : "text-primary"}`}>
                      {authorLabel(v)}
                    </div>
                    <div className={`text-xs font-semibold ${selected?.id === v.id ? "text-brand-text" : "text-subtle"}`}>
                      {when(v.created_at)}
                    </div>
                  </div>
                </button>
              </li>
            ))}
          </ol>
        </>
      )}
    </aside>
  );
}

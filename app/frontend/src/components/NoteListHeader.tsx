import { ChevronLeft, Search, X } from "lucide-react";
import type { Space } from "../api/types";
import { useFolders, useItems, useTags } from "../api/hooks";
import { t, tn } from "../i18n";
import { tagColor } from "../lib/tagColor";

// Шапка списка заметок на телефоне (макет «Список заметок», 21.10): назад,
// путь (спейс › родительская папка), поиск; ниже — плитка папки с эмодзи,
// название и счётчики; строка пилюль — подпапки и самые частые теги.
// Данные — те же запросы, что у NoteList и экрана папок, то есть из кэша.
export default function NoteListHeader({
  space,
  folderId,
  tagId,
  searchOpen,
  onToggleSearch,
  onBack,
  onSelectFolder,
  onSelectTag,
}: {
  space: Space | undefined;
  // null — «Все заметки», "root" — «Без папки».
  folderId: string | null;
  tagId: string | null;
  searchOpen: boolean;
  onToggleSearch: () => void;
  onBack: () => void;
  onSelectFolder: (folderId: string | null) => void;
  onSelectTag: (tagId: string | null) => void;
}) {
  const { data: folders } = useFolders(tagId ? undefined : space?.id);
  const { data: items } = useItems(tagId ? undefined : space?.id, tagId ? null : folderId, tagId);
  const { data: tags } = useTags();

  const all = folders ?? [];
  const folder = folderId && folderId !== "root" ? all.find((f) => f.id === folderId) : undefined;
  const parent = folder?.parent_id ? all.find((f) => f.id === folder.parent_id) : undefined;
  const tag = tagId ? tags?.find((x) => x.id === tagId) : undefined;

  const title = tagId
    ? `#${tag?.name ?? ""}`
    : folderId === "root"
      ? t("folders.root")
      : folder
        ? folder.name
        : t("folders.all");
  const children = tagId ? [] : folder ? all.filter((f) => f.parent_id === folder.id) : folderId === null ? all.filter((f) => f.parent_id === null) : [];

  // Теги по частоте среди заметок на экране — быстрый фильтр.
  const tagCounts = new Map<string, { name: string; n: number }>();
  for (const item of items ?? []) {
    for (const x of item.tags) {
      const cur = tagCounts.get(x.id);
      if (cur) cur.n += 1;
      else tagCounts.set(x.id, { name: x.name, n: 1 });
    }
  }
  const topTags = Array.from(tagCounts.entries())
    .sort((a, b) => b[1].n - a[1].n)
    .slice(0, 5);

  const crumb = tagId ? t("nav.tags") : parent ? `${space?.name ?? ""} › ${parent.name}` : (space?.name ?? "");

  const pill = (active: boolean) =>
    `flex h-9 shrink-0 items-center gap-1 rounded-full px-3 text-[13px] font-bold transition-colors ${
      active ? "bg-accent text-on-accent" : "bg-surface text-primary shadow-card"
    }`;

  return (
    <div>
      {/* Строка «назад · путь · поиск» — только телефон: на десктопе путь
          виден в дереве слева, а поиск всегда раскрыт. */}
      <div className="flex items-center gap-2 px-3 pt-3 lg:hidden">
        <button
          onClick={onBack}
          aria-label={t("nav.back")}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card"
        >
          <ChevronLeft size={20} strokeWidth={2.4} />
        </button>
        <div className="min-w-0 flex-1 truncate text-[13px] font-bold text-subtle">{crumb}</div>
        <button
          onClick={onToggleSearch}
          aria-label={t("common.search")}
          aria-pressed={searchOpen}
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl shadow-card ${
            searchOpen ? "bg-accent text-on-accent" : "bg-surface text-primary"
          }`}
        >
          {searchOpen ? <X size={20} strokeWidth={2.4} /> : <Search size={20} strokeWidth={2.4} />}
        </button>
      </div>
      <div className="flex items-center gap-3 px-5 pt-2.5">
        <span
          className={`flex h-[52px] w-[52px] shrink-0 items-center justify-center rounded-2xl text-2xl leading-none ${
            folder ? "bg-brand text-white" : "bg-surface text-primary shadow-card"
          }`}
        >
          {tagId ? "#" : folder ? (folder.icon ?? "📁") : folderId === "root" ? "📄" : "🗂️"}
        </span>
        <div className="min-w-0">
          <h1 className="truncate text-[28px] font-extrabold leading-tight tracking-tight text-primary">{title}</h1>
          <div className="text-[13px] font-semibold text-subtle">
            {items ? tn("count.notes", items.length) : "…"}
            {children.length > 0 ? ` · ${tn("count.subfolders", children.length)}` : ""}
          </div>
        </div>
      </div>
      {(children.length > 0 || topTags.length > 0) && (
        <div className="flex gap-2 overflow-x-auto px-5 pt-3.5" style={{ scrollbarWidth: "none" }}>
          <button onClick={() => (tagId ? onSelectTag(null) : undefined)} className={pill(true)}>
            {t("spaces.all")}
          </button>
          {children.map((child) => (
            <button key={child.id} onClick={() => onSelectFolder(child.id)} className={pill(false)}>
              <span aria-hidden="true">{child.icon ?? "📁"}</span> {child.name}
            </button>
          ))}
          {topTags.map(([id, x]) => (
            <button key={id} onClick={() => onSelectTag(id)} className={`${pill(false)} ${tagColor(x.name).chip}`}>
              #{x.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

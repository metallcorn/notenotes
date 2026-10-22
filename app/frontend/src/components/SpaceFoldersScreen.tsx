import { useState } from "react";
import { ChevronDown, ChevronRight, LockOpen, Users } from "lucide-react";
import type { Folder, Space } from "../api/types";
import { useFolders, useItems, useSpaceMembers } from "../api/hooks";
import { lockVault, useVaultUnlocked } from "../lib/vaultSession";
import { useLongPress } from "../lib/useLongPress";
import FolderActionsSheet from "./FolderActionsSheet";
import NewFolderDialog from "./NewFolderDialog";
import SpaceMembersModal from "./SpaceMembersModal";
import VaultUnlockOverlay from "./VaultUnlockOverlay";
import { ListSkeleton } from "./Skeleton";
import { t } from "../i18n";

function FolderRow({
  folder,
  all,
  depth,
  countIn,
  selectedFolderId,
  expanded,
  onToggle,
  onSelect,
  onActions,
  dark,
}: {
  folder: Folder;
  all: Folder[];
  depth: number;
  countIn: (id: string | null) => number;
  selectedFolderId: string | null | undefined;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
  onActions: (folder: Folder) => void;
  dark: boolean;
}) {
  const children = all.filter((f) => f.parent_id === folder.id);
  const isOpen = expanded.has(folder.id);
  const selected = selectedFolderId === folder.id;
  const { handlers, guard } = useLongPress(() => onActions(folder));
  return (
    <li>
      <div
        className={`flex min-h-[52px] items-center rounded-2xl transition-colors ${
          selected ? (dark ? "bg-white/10" : "bg-brand-soft") : ""
        }`}
      >
        <button
          type="button"
          {...handlers}
          onClick={guard(() => onSelect(folder.id))}
          style={{ WebkitTouchCallout: "none" }}
          className="flex min-h-[52px] min-w-0 flex-1 select-none items-center gap-3 pl-2.5 text-left"
        >
          <span
            className={`flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-xl text-base leading-none ${
              selected ? "bg-brand text-white" : dark ? "bg-white/10" : "bg-muted"
            }`}
          >
            {folder.icon ?? "📁"}
          </span>
          <span
            className={`min-w-0 flex-1 truncate font-extrabold ${depth > 0 ? "text-[15px]" : "text-base"} ${
              dark ? "text-nav-text" : "text-primary"
            }`}
          >
            {folder.name}
          </span>
          <span className={`shrink-0 text-[13px] font-bold ${selected ? "text-brand-text" : dark ? "text-nav-muted" : "text-subtle"}`}>
            {countIn(folder.id)}
          </span>
        </button>
        <button
          type="button"
          aria-label={children.length > 0 ? (isOpen ? "Свернуть" : "Развернуть") : t("folders.actions")}
          onClick={() => (children.length > 0 ? onToggle(folder.id) : onActions(folder))}
          className={`flex h-[52px] w-11 shrink-0 items-center justify-center ${
            selected ? "text-brand-text" : dark ? "text-nav-muted" : "text-subtle"
          }`}
        >
          {children.length > 0 ? (
            isOpen ? <ChevronDown size={16} strokeWidth={2.6} /> : <ChevronRight size={16} strokeWidth={2.6} />
          ) : (
            <ChevronRight size={16} strokeWidth={2.6} />
          )}
        </button>
      </div>
      {children.length > 0 && isOpen && (
        <ul className={`mb-1 ml-[26px] mt-0.5 border-l-2 pl-3 ${dark ? "border-white/10" : "border-brand-soft"}`}>
          {children.map((child) => (
            <FolderRow
              key={child.id}
              folder={child}
              all={all}
              depth={depth + 1}
              countIn={countIn}
              selectedFolderId={selectedFolderId}
              expanded={expanded}
              onToggle={onToggle}
              onSelect={onSelect}
              onActions={onActions}
              dark={dark}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

// Экран спейса на телефоне (макет «Папки спейса», 21.10): шапка со
// спейсом (тап — шторка выбора спейса), участники, две большие карточки
// «Все заметки»/«Без папки», список папок с эмодзи и счётчиками. Долгое
// нажатие на папку — шторка действий. Сейф — тот же экран в тёмном.
export default function SpaceFoldersScreen({
  space,
  selectedFolderId,
  onSelectFolder,
  onOpenSpaces,
}: {
  space: Space;
  selectedFolderId: string | null;
  // null — «Все заметки», "root" — «Без папки» (как в FolderTree).
  onSelectFolder: (folderId: string | null) => void;
  onOpenSpaces: () => void;
}) {
  const unlocked = useVaultUnlocked(space.is_vault ? space.id : undefined);
  const locked = space.is_vault && !unlocked;
  const { data: folders } = useFolders(locked ? undefined : space.id);
  const { data: items } = useItems(locked ? undefined : space.id);
  const { data: members } = useSpaceMembers(space.id);
  const [actions, setActions] = useState<Folder | null>(null);
  const [creating, setCreating] = useState(false);
  const [membersOpen, setMembersOpen] = useState(false);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const dark = space.is_vault;
  const all = folders ?? [];
  const roots = all.filter((f) => f.parent_id === null);
  const countIn = (id: string | null) => (items ?? []).filter((i) => i.folder_id === id).length;
  const initial = (space.name.trim()[0] ?? "?").toUpperCase();

  function toggle(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  return (
    <div className={`flex min-h-0 flex-1 flex-col overflow-y-auto ${dark ? "bg-nav text-nav-text" : ""}`}>
      <div className="flex items-center gap-2.5 px-4 pt-4">
        <button
          type="button"
          onClick={onOpenSpaces}
          aria-label={t("spaces.pick")}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <span
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl text-lg font-extrabold ${
              dark ? "bg-white/10 text-lime" : "bg-lime text-on-lime"
            }`}
          >
            {initial}
          </span>
          <span className={`truncate text-[26px] font-extrabold tracking-tight ${dark ? "text-nav-text" : "text-primary"}`}>
            {space.name}
          </span>
          <ChevronDown size={20} strokeWidth={2.4} className={`shrink-0 ${dark ? "text-nav-muted" : "text-subtle"}`} />
        </button>
        {dark && unlocked ? (
          <button
            type="button"
            onClick={() => lockVault(space.id)}
            className="flex h-11 shrink-0 items-center gap-1.5 rounded-2xl bg-lime px-3.5 text-sm font-extrabold text-on-lime"
          >
            <LockOpen size={16} /> {t("vault.close")}
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setMembersOpen(true)}
            aria-label={t("folders.members")}
            className={`flex h-11 shrink-0 items-center gap-1.5 rounded-2xl px-3 text-sm font-extrabold ${
              dark ? "bg-white/10 text-nav-text" : "bg-surface text-primary shadow-card"
            }`}
          >
            <Users size={18} strokeWidth={2.2} /> {members?.length ?? ""}
          </button>
        )}
      </div>

      {locked ? (
        <VaultUnlockOverlay spaceId={space.id} spaceName={space.name} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2.5 px-4 pt-4">
            <button
              type="button"
              onClick={() => onSelectFolder(null)}
              className={`flex flex-col gap-1 rounded-2xl p-3.5 text-left ${
                dark ? "bg-white/10 text-nav-text" : "bg-nav text-nav-text"
              } ${selectedFolderId === null ? "ring-2 ring-lime" : ""}`}
            >
              <span className="text-[26px] font-extrabold leading-none tracking-tight">{items ? items.length : "…"}</span>
              <span className="text-[13px] font-bold text-nav-muted">{t("folders.all")}</span>
            </button>
            <button
              type="button"
              onClick={() => onSelectFolder("root")}
              className={`flex flex-col gap-1 rounded-2xl p-3.5 text-left ${
                dark ? "bg-white/10 text-nav-text" : "bg-surface text-primary shadow-card"
              } ${selectedFolderId === "root" ? "ring-2 ring-brand" : ""}`}
            >
              <span className="text-[26px] font-extrabold leading-none tracking-tight">{items ? countIn(null) : "…"}</span>
              <span className={`text-[13px] font-bold ${dark ? "text-nav-muted" : "text-subtle"}`}>{t("folders.root")}</span>
            </button>
          </div>

          <div className="flex items-center justify-between px-4 pb-2.5 pt-5">
            <h2 className={`text-lg font-extrabold ${dark ? "text-nav-text" : "text-primary"}`}>{t("folders.title")}</h2>
            <button
              type="button"
              onClick={() => setCreating(true)}
              className={`h-9 rounded-full border-[1.5px] px-3.5 text-sm font-extrabold ${
                dark ? "border-nav-text text-nav-text" : "border-primary text-primary"
              }`}
            >
              {t("folders.new")}
            </button>
          </div>

          {!folders ? (
            <div className="px-4">
              <ListSkeleton rows={4} withIcon={false} />
            </div>
          ) : roots.length === 0 ? (
            <div className={`mx-4 rounded-2xl p-4 text-center text-sm font-semibold ${dark ? "bg-white/10 text-nav-muted" : "bg-surface text-subtle shadow-card"}`}>
              Папок пока нет
            </div>
          ) : (
            <ul className={`mx-4 rounded-2xl p-1.5 ${dark ? "bg-white/5" : "bg-surface shadow-card"}`}>
              {roots.map((folder) => (
                <FolderRow
                  key={folder.id}
                  folder={folder}
                  all={all}
                  depth={0}
                  countIn={countIn}
                  selectedFolderId={selectedFolderId}
                  expanded={expanded}
                  onToggle={toggle}
                  onSelect={onSelectFolder}
                  onActions={setActions}
                  dark={dark}
                />
              ))}
            </ul>
          )}
          <p className={`px-4 pb-4 pt-3 text-[13px] font-semibold leading-snug ${dark ? "text-nav-muted" : "text-subtle"}`}>
            {t("folders.hint")}
          </p>
        </>
      )}

      {actions && (
        <FolderActionsSheet
          folder={actions}
          notesCount={countIn(actions.id)}
          subfoldersCount={all.filter((f) => f.parent_id === actions.id).length}
          onClose={() => setActions(null)}
          onDeleted={() => {
            if (selectedFolderId === actions.id) onSelectFolder(null);
          }}
        />
      )}
      {creating && <NewFolderDialog spaceId={space.id} parent={null} onClose={() => setCreating(false)} />}
      {membersOpen && <SpaceMembersModal spaceId={space.id} spaceName={space.name} onClose={() => setMembersOpen(false)} />}
    </div>
  );
}

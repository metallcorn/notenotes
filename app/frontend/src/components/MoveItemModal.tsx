import { useEffect, useState } from "react";
import { Check, Lock, X } from "lucide-react";
import { useFolders } from "../api/hooks";
import type { Folder, Space } from "../api/types";
import { t } from "../i18n";

// Реальная жалоба: раньше перенос заметки в другой спейс и раскладывание
// по папке были двумя отдельными, никак не связанными шагами (перенести —
// подождать — открыть заметку заново — выбрать папку из дропдауна). Один
// модал: выбрал спейс — сразу видно его папки — кликнул — готово. Только
// клики, без drag-and-drop — по прямому запросу должно одинаково удобно
// работать и на мобиле.
//
// Вторая реальная жалоба (пришла сразу после первого деплоя): текущий
// спейс не попадал в список вообще — казалось логичным, что "переместить"
// не может значить "остаться там же", но частый случай — переложить в
// ДРУГУЮ (вложенную) папку ВНУТРИ того же спейса, где сейчас открыта
// заметка. Текущий спейс теперь в списке и выбран по умолчанию; папки —
// настоящее дерево (как в FolderTree.tsx), не плоский список, иначе
// одноимённые вложенные папки было не отличить друг от друга.
//
// Макет «Куда положить?» (21.10): шторка снизу, спейсы — пилюлями, папки —
// строками со значком и галочкой, большая кнопка «Перенести в …» внизу.

type Target = { spaceId: string; folderId: string | null };

function FolderOption({
  folder,
  all,
  depth,
  spaceId,
  current,
  target,
  onPick,
}: {
  folder: Folder;
  all: Folder[];
  depth: number;
  spaceId: string;
  current: Target;
  target: Target | null;
  onPick: (t: Target) => void;
}) {
  const children = all.filter((f) => f.parent_id === folder.id);
  const isCurrent = spaceId === current.spaceId && folder.id === current.folderId;
  const picked = target?.spaceId === spaceId && target.folderId === folder.id;
  return (
    <>
      <button
        onClick={() => onPick({ spaceId, folderId: folder.id })}
        disabled={isCurrent}
        style={{ paddingLeft: `${12 + depth * 18}px` }}
        className={`flex min-h-[52px] w-full items-center gap-3 rounded-2xl pr-3 text-left transition-colors disabled:cursor-default ${
          picked ? "border-2 border-brand bg-brand-soft" : "hover:bg-muted"
        } ${isCurrent ? "opacity-50" : ""}`}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-muted text-base leading-none">
          {folder.icon ?? "📁"}
        </span>
        <span className={`min-w-0 flex-1 truncate text-[15px] ${picked ? "font-extrabold text-brand-text" : "font-bold text-primary"}`}>
          {folder.name}
          {isCurrent && <span className="ml-1 text-xs font-semibold text-subtle">({t("move.here")})</span>}
        </span>
        {picked && (
          <span className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full bg-brand text-white">
            <Check size={14} strokeWidth={3} />
          </span>
        )}
      </button>
      {children.map((child) => (
        <FolderOption key={child.id} folder={child} all={all} depth={depth + 1} spaceId={spaceId} current={current} target={target} onPick={onPick} />
      ))}
    </>
  );
}

export default function MoveItemModal({
  spaces,
  currentSpaceId,
  currentFolderId,
  itemTitle,
  onMove,
  onSelectVaultSpace,
  onClose,
}: {
  spaces: Space[];
  currentSpaceId: string;
  currentFolderId: string | null;
  itemTitle?: string;
  onMove: (spaceId: string, folderId: string | null) => void;
  onSelectVaultSpace: (spaceId: string) => void;
  onClose: () => void;
}) {
  const [spaceId, setSpaceId] = useState<string>(currentSpaceId);
  const [target, setTarget] = useState<Target | null>(null);
  const { data: folders, isLoading: foldersLoading } = useFolders(spaceId);
  const roots = (folders ?? []).filter((f) => f.parent_id === null);
  const current: Target = { spaceId: currentSpaceId, folderId: currentFolderId };
  const space = spaces.find((s) => s.id === spaceId);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const targetName = target
    ? target.folderId
      ? (folders ?? []).find((f) => f.id === target.folderId)?.name ?? ""
      : `${space?.name ?? ""} · ${t("folders.root")}`
    : "";
  const rootIsCurrent = spaceId === currentSpaceId && currentFolderId === null;
  const rootPicked = target?.spaceId === spaceId && target.folderId === null;

  return (
    <div
      className="modal-in fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("move.title")}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="sheet-in flex max-h-[88dvh] w-full max-w-md flex-col rounded-t-3xl bg-surface px-4 pb-[max(20px,var(--safe-bottom))] pt-2.5 shadow-xl sm:rounded-3xl sm:pb-5"
      >
        <div className="mx-auto mb-3 h-[5px] w-10 shrink-0 rounded-full bg-muted-active sm:hidden" aria-hidden="true" />
        <div className="flex shrink-0 items-start justify-between gap-2 px-1">
          <div className="min-w-0">
            {itemTitle !== undefined && (
              <div className="truncate text-[13px] font-bold text-subtle">{t("move.what", { title: itemTitle || "Без названия" })}</div>
            )}
            <h2 className="text-2xl font-extrabold tracking-tight text-primary">{t("move.title")}</h2>
          </div>
          <button onClick={onClose} aria-label="Закрыть" className="hidden h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-muted text-primary hover:bg-muted-hover sm:flex">
            <X size={18} />
          </button>
        </div>

        <div className="-mx-4 mt-3.5 flex shrink-0 gap-2 overflow-x-auto px-4" style={{ scrollbarWidth: "none" }}>
          {spaces.map((s) => (
            <button
              key={s.id}
              onClick={() => {
                if (s.is_vault) {
                  onSelectVaultSpace(s.id);
                  return;
                }
                setSpaceId(s.id);
                setTarget(null);
              }}
              className={`flex h-10 shrink-0 items-center gap-1.5 rounded-full px-4 text-sm font-extrabold transition-colors ${
                s.id === spaceId ? "bg-accent text-on-accent" : "bg-muted text-primary hover:bg-muted-hover"
              }`}
            >
              {s.is_vault && <Lock size={13} />}
              {s.name}
            </button>
          ))}
        </div>

        <div className="mt-3.5 min-h-0 flex-1 space-y-1 overflow-y-auto">
          <button
            onClick={() => setTarget({ spaceId, folderId: null })}
            disabled={rootIsCurrent}
            className={`flex min-h-[52px] w-full items-center gap-3 rounded-2xl px-3 text-left transition-colors disabled:cursor-default ${
              rootPicked ? "border-2 border-brand bg-brand-soft" : "hover:bg-muted"
            } ${rootIsCurrent ? "opacity-50" : ""}`}
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-muted text-base leading-none">📄</span>
            <span className={`min-w-0 flex-1 truncate text-[15px] ${rootPicked ? "font-extrabold text-brand-text" : "font-bold text-primary"}`}>
              {t("folders.root")}
              {rootIsCurrent && <span className="ml-1 text-xs font-semibold text-subtle">({t("move.here")})</span>}
            </span>
            {rootPicked && (
              <span className="flex h-[26px] w-[26px] shrink-0 items-center justify-center rounded-full bg-brand text-white">
                <Check size={14} strokeWidth={3} />
              </span>
            )}
          </button>
          {foldersLoading && <div className="px-3 py-2 text-xs font-semibold text-subtle">Загрузка…</div>}
          {roots.map((folder) => (
            <FolderOption
              key={folder.id}
              folder={folder}
              all={folders ?? []}
              depth={0}
              spaceId={spaceId}
              current={current}
              target={target}
              onPick={setTarget}
            />
          ))}
        </div>

        <button
          onClick={() => target && onMove(target.spaceId, target.folderId)}
          disabled={!target}
          className="mt-3.5 h-14 w-full shrink-0 truncate rounded-2xl bg-accent px-4 text-base font-extrabold text-on-accent disabled:opacity-40"
        >
          {target ? t("move.cta", { target: targetName }) : t("move.title")}
        </button>
        <div className="mt-2 shrink-0 text-center text-xs font-semibold text-subtle">{t("move.hint")}</div>
      </div>
    </div>
  );
}

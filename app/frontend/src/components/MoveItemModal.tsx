import { useState } from "react";
import { ChevronRight, Folder as FolderIcon, X } from "lucide-react";
import { useFolders } from "../api/hooks";
import type { Folder, Space } from "../api/types";

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
// заметка. Текущий спейс теперь в списке и раскрыт по умолчанию; папки —
// настоящее дерево (как в FolderTree.tsx), не плоский список, иначе
// одноимённые вложенные папки было не отличить друг от друга.

function FolderOption({
  folder,
  all,
  depth,
  spaceId,
  currentSpaceId,
  currentFolderId,
  onMove,
}: {
  folder: Folder;
  all: Folder[];
  depth: number;
  spaceId: string;
  currentSpaceId: string;
  currentFolderId: string | null;
  onMove: (spaceId: string, folderId: string | null) => void;
}) {
  const children = all.filter((f) => f.parent_id === folder.id);
  const isCurrent = spaceId === currentSpaceId && folder.id === currentFolderId;
  return (
    <>
      <button
        onClick={() => onMove(spaceId, folder.id)}
        disabled={isCurrent}
        style={{ paddingLeft: `${24 + depth * 16}px` }}
        className={`flex min-h-11 w-full items-center gap-2 pr-4 text-left text-sm font-semibold hover:bg-muted disabled:cursor-default disabled:hover:bg-transparent ${
          isCurrent ? "text-subtle" : "text-secondary"
        }`}
      >
        <FolderIcon size={13} className="shrink-0 text-subtle" />
        <span className="truncate">{folder.name}</span>
        {isCurrent && <span className="text-xs text-subtle">(здесь)</span>}
      </button>
      {children.map((child) => (
        <FolderOption
          key={child.id}
          folder={child}
          all={all}
          depth={depth + 1}
          spaceId={spaceId}
          currentSpaceId={currentSpaceId}
          currentFolderId={currentFolderId}
          onMove={onMove}
        />
      ))}
    </>
  );
}

export default function MoveItemModal({
  spaces,
  currentSpaceId,
  currentFolderId,
  onMove,
  onSelectVaultSpace,
  onClose,
}: {
  spaces: Space[];
  currentSpaceId: string;
  currentFolderId: string | null;
  onMove: (spaceId: string, folderId: string | null) => void;
  onSelectVaultSpace: (spaceId: string) => void;
  onClose: () => void;
}) {
  const [expandedSpaceId, setExpandedSpaceId] = useState<string | null>(currentSpaceId);
  const { data: folders, isLoading: foldersLoading } = useFolders(expandedSpaceId ?? undefined);
  const roots = (folders ?? []).filter((f) => f.parent_id === null);

  return (
    <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[80vh] w-full max-w-sm flex-col overflow-hidden rounded-3xl bg-surface shadow-xl"
      >
        <div className="flex items-center justify-between px-5 py-4">
          <div className="text-2xl font-extrabold tracking-tight text-primary">Куда положить</div>
          <button onClick={onClose} aria-label="Закрыть" className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-primary hover:bg-muted-hover">
            <X size={18} />
          </button>
        </div>
        <div className="overflow-y-auto px-3 pb-3">
          {spaces.map((space) => {
            const expanded = expandedSpaceId === space.id;
            const isCurrentSpace = space.id === currentSpaceId;
            return (
              <div key={space.id} className="mb-1.5 overflow-hidden rounded-2xl bg-muted">
                <button
                  onClick={() => {
                    if (space.is_vault) {
                      onSelectVaultSpace(space.id);
                      return;
                    }
                    setExpandedSpaceId(expanded ? null : space.id);
                  }}
                  className="flex min-h-12 w-full items-center justify-between gap-2 px-4 text-left text-[15px] font-extrabold text-primary hover:bg-muted-hover"
                >
                  <span className="truncate">
                    {space.name}
                    {isCurrentSpace && <span className="text-xs text-subtle"> (текущий)</span>}
                    {space.is_vault && " 🔒"}
                  </span>
                  {!space.is_vault && (
                    <ChevronRight size={14} className={`shrink-0 text-subtle transition-transform ${expanded ? "rotate-90" : ""}`} />
                  )}
                </button>
                {expanded && (
                  <div className="bg-surface pb-1 pt-1">
                    <button
                      onClick={() => onMove(space.id, null)}
                      disabled={isCurrentSpace && currentFolderId === null}
                      className={`flex min-h-11 w-full items-center gap-2 px-6 text-left text-sm font-semibold hover:bg-muted disabled:cursor-default disabled:hover:bg-transparent ${
                        isCurrentSpace && currentFolderId === null ? "text-subtle" : "text-secondary"
                      }`}
                    >
                      Без папки {isCurrentSpace && currentFolderId === null && <span className="text-xs">(здесь)</span>}
                    </button>
                    {foldersLoading && <div className="px-6 py-2 text-xs text-subtle">Загрузка…</div>}
                    {roots.map((folder) => (
                      <FolderOption
                        key={folder.id}
                        folder={folder}
                        all={folders ?? []}
                        depth={0}
                        spaceId={space.id}
                        currentSpaceId={currentSpaceId}
                        currentFolderId={currentFolderId}
                        onMove={onMove}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

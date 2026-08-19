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
        className={`flex w-full items-center gap-2 py-2 pr-4 text-left text-sm hover:bg-slate-100 disabled:cursor-default disabled:hover:bg-transparent ${
          isCurrent ? "font-medium text-slate-400" : "text-slate-700"
        }`}
      >
        <FolderIcon size={13} className="shrink-0 text-slate-400" />
        <span className="truncate">{folder.name}</span>
        {isCurrent && <span className="text-xs text-slate-400">(здесь)</span>}
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[80vh] w-full max-w-sm flex-col overflow-hidden rounded-lg bg-white shadow-xl"
      >
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="text-sm font-medium text-slate-900">Переместить в…</div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-700">
            <X size={16} />
          </button>
        </div>
        <div className="overflow-y-auto">
          {spaces.map((space) => {
            const expanded = expandedSpaceId === space.id;
            const isCurrentSpace = space.id === currentSpaceId;
            return (
              <div key={space.id} className="border-b last:border-b-0">
                <button
                  onClick={() => {
                    if (space.is_vault) {
                      onSelectVaultSpace(space.id);
                      return;
                    }
                    setExpandedSpaceId(expanded ? null : space.id);
                  }}
                  className="flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left text-sm text-slate-900 hover:bg-slate-50"
                >
                  <span className="truncate">
                    {space.name}
                    {isCurrentSpace && <span className="text-xs text-slate-400"> (текущий)</span>}
                    {space.is_vault && " 🔒"}
                  </span>
                  {!space.is_vault && (
                    <ChevronRight size={14} className={`shrink-0 text-slate-400 transition-transform ${expanded ? "rotate-90" : ""}`} />
                  )}
                </button>
                {expanded && (
                  <div className="bg-slate-50 pb-1">
                    <button
                      onClick={() => onMove(space.id, null)}
                      disabled={isCurrentSpace && currentFolderId === null}
                      className={`flex w-full items-center gap-2 px-6 py-2 text-left text-sm hover:bg-slate-100 disabled:cursor-default disabled:hover:bg-transparent ${
                        isCurrentSpace && currentFolderId === null ? "font-medium text-slate-400" : "text-slate-700"
                      }`}
                    >
                      Без папки {isCurrentSpace && currentFolderId === null && <span className="text-xs">(здесь)</span>}
                    </button>
                    {foldersLoading && <div className="px-6 py-2 text-xs text-slate-400">Загрузка…</div>}
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

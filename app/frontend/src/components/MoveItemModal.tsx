import { useState } from "react";
import { ChevronRight, Folder as FolderIcon, X } from "lucide-react";
import { useFolders } from "../api/hooks";
import type { Space } from "../api/types";

// Реальная жалоба: раньше перенос заметки в другой спейс и раскладывание
// по папке были двумя отдельными, никак не связанными шагами (перенести —
// подождать — открыть заметку заново — выбрать папку из дропдауна). Один
// модал: выбрал спейс — сразу видно его папки — кликнул — готово. Только
// клики, без drag-and-drop — по прямому запросу должно одинаково удобно
// работать и на мобиле.
export default function MoveItemModal({
  spaces,
  onMove,
  onSelectVaultSpace,
  onClose,
}: {
  spaces: Space[];
  onMove: (spaceId: string, folderId: string | null) => void;
  onSelectVaultSpace: (spaceId: string) => void;
  onClose: () => void;
}) {
  const [expandedSpaceId, setExpandedSpaceId] = useState<string | null>(null);
  const { data: folders, isLoading: foldersLoading } = useFolders(expandedSpaceId ?? undefined);

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
                      className="flex w-full items-center gap-2 px-6 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
                    >
                      Без папки
                    </button>
                    {foldersLoading && <div className="px-6 py-2 text-xs text-slate-400">Загрузка…</div>}
                    {(folders ?? []).map((folder) => (
                      <button
                        key={folder.id}
                        onClick={() => onMove(space.id, folder.id)}
                        className="flex w-full items-center gap-2 px-6 py-2 text-left text-sm text-slate-700 hover:bg-slate-100"
                      >
                        <FolderIcon size={13} className="shrink-0 text-slate-400" />
                        <span className="truncate">{folder.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          {spaces.length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-slate-400">Больше некуда — доступен только этот спейс.</div>
          )}
        </div>
      </div>
    </div>
  );
}

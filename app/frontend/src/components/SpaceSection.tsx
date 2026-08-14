import { useState } from "react";
import { Lock, Pencil } from "lucide-react";
import type { Space } from "../api/types";
import { useUpdateSpace } from "../api/hooks";
import { useVaultUnlocked } from "../lib/vaultSession";
import FolderTree from "./FolderTree";
import PromptDialog from "./PromptDialog";
import VaultUnlockOverlay from "./VaultUnlockOverlay";

export default function SpaceSection({
  space,
  isActive,
  activeFolderId,
  collapsed,
  onToggleCollapse,
  onSelectFolder,
}: {
  space: Space;
  isActive: boolean;
  activeFolderId: string | null;
  collapsed: boolean;
  onToggleCollapse: () => void;
  onSelectFolder: (spaceId: string, folderId: string | null) => void;
}) {
  const updateSpace = useUpdateSpace();
  const [renaming, setRenaming] = useState(false);
  const unlocked = useVaultUnlocked(space.is_vault ? space.id : undefined);

  return (
    <div className="mb-3">
      <div className="flex items-center gap-0.5">
        <button
          onClick={onToggleCollapse}
          className="flex min-w-0 flex-1 items-center gap-1 rounded px-1 py-1 text-left text-sm font-semibold text-slate-800 hover:bg-slate-100"
        >
          <span
            className={`inline-block w-3 shrink-0 text-slate-400 transition-transform ${collapsed ? "" : "rotate-90"}`}
          >
            &#9656;
          </span>
          {space.is_vault && (
            <Lock size={12} className={`shrink-0 ${unlocked ? "text-amber-500" : "text-slate-400"}`} />
          )}
          <span className="truncate">{space.name}</span>
        </button>
        <button
          title="Переименовать спейс"
          onClick={() => setRenaming(true)}
          className="flex h-6 w-6 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700"
        >
          <Pencil size={12} />
        </button>
      </div>
      {!collapsed && space.is_vault && !unlocked && (
        <div className="ml-3">
          <VaultUnlockOverlay spaceId={space.id} spaceName={space.name} compact />
        </div>
      )}
      {!collapsed && (!space.is_vault || unlocked) && (
        <div className="ml-3">
          <FolderTree
            spaceId={space.id}
            selectedFolderId={isActive ? activeFolderId : undefined}
            onSelect={(folderId) => onSelectFolder(space.id, folderId)}
          />
        </div>
      )}

      {renaming && (
        <PromptDialog
          title={`Переименовать спейс «${space.name}»`}
          initialValue={space.name}
          onConfirm={(name) => {
            if (name !== space.name) updateSpace.mutate({ id: space.id, name });
            setRenaming(false);
          }}
          onCancel={() => setRenaming(false)}
        />
      )}
    </div>
  );
}

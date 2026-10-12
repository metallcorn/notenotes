import { useState } from "react";
import { useMoveFolderSpace, useSpaces } from "../api/hooks";
import type { Folder } from "../api/types";
import ConfirmDialog from "./ConfirmDialog";

// Реальная жалоба: перенести ЦЕЛУЮ папку (со всеми заметками/списками/
// таблицами и вложенными папками) в другой спейс было нельзя вообще —
// только заметку за заметкой. Список спейсов, затем подтверждение — тот
// же двухшаговый паттерн, что у переноса заметки в NoteEditor.tsx, только
// отдельным модальным окном (в дереве папок нет места под инлайновый
// <select>, как там).
export default function FolderMoveModal({
  folder,
  onClose,
  onMoved,
}: {
  folder: Folder;
  onClose: () => void;
  onMoved: () => void;
}) {
  const { data: spaces } = useSpaces();
  const moveFolder = useMoveFolderSpace();
  const [targetSpaceId, setTargetSpaceId] = useState<string | null>(null);

  // Сейф не поддерживает массовый перенос (routers/folders.py::move_folder_space
  // — шифрование на клиенте, не пакетное).
  const candidates = (spaces ?? []).filter((s) => s.id !== folder.space_id && !s.is_vault);
  const targetSpace = candidates.find((s) => s.id === targetSpaceId);

  if (targetSpaceId && targetSpace) {
    return (
      <ConfirmDialog
        title={`Перенести папку «${folder.name}» со всем содержимым в спейс «${targetSpace.name}»?`}
        confirmLabel="Перенести"
        onConfirm={async () => {
          await moveFolder.mutateAsync({ id: folder.id, space_id: targetSpaceId });
          onMoved();
          onClose();
        }}
        onCancel={() => setTargetSpaceId(null)}
      />
    );
  }

  return (
    <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-lg bg-surface p-4 shadow-xl">
        <div className="mb-1 text-sm font-medium text-primary">Перенести папку «{folder.name}»</div>
        <div className="mb-3 text-xs text-subtle">
          Все заметки, списки, таблицы и вложенные папки внутри переедут вместе с ней.
        </div>
        {candidates.length === 0 ? (
          <div className="text-sm text-subtle">Нет других доступных спейсов (сейфы не поддерживаются)</div>
        ) : (
          <ul className="max-h-64 space-y-0.5 overflow-y-auto">
            {candidates.map((space) => (
              <li key={space.id}>
                <button
                  onClick={() => setTargetSpaceId(space.id)}
                  className="block w-full rounded px-2 py-1.5 text-left text-sm text-secondary hover:bg-muted-hover"
                >
                  {space.name}
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-3 flex justify-end">
          <button onClick={onClose} className="rounded px-3 py-1.5 text-sm text-subtle hover:bg-muted-hover">
            Отмена
          </button>
        </div>
      </div>
    </div>
  );
}

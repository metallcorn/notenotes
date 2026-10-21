import { useState } from "react";
import { Globe, KeyRound, Lock, LockOpen, MoreVertical, Pencil, Trash2, Users } from "lucide-react";
import type { Space } from "../api/types";
import { useDeleteSpace, useSpaceMembers, useUpdateSpace } from "../api/hooks";
import { ApiError } from "../api/client";
import { lockVault, useVaultUnlocked } from "../lib/vaultSession";
import FolderTree from "./FolderTree";
import PromptDialog from "./PromptDialog";
import SpaceMembersModal from "./SpaceMembersModal";
import VaultChangePasswordModal from "./VaultChangePasswordModal";
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
  const deleteSpace = useDeleteSpace();
  const [renaming, setRenaming] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const [managingMembers, setManagingMembers] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Непустой спейс сервер отклоняет без force (400) — тогда предлагаем
  // принудительное удаление, но только через отдельный чекбокс ниже: по
  // явной просьбе, чтобы случайное удаление было буквально невозможным.
  const [needsForce, setNeedsForce] = useState(false);
  const [forceConfirmed, setForceConfirmed] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const unlocked = useVaultUnlocked(space.is_vault ? space.id : undefined);
  // Реальный запрос: хотел видеть сразу, что спейс шаренный, не открывая
  // «Участники спейса» — тот же приём, что уже есть у сейфа (Lock рядом с
  // названием), просто триггер "количество участников > 1", а не is_vault.
  const members = useSpaceMembers(space.id);
  const isShared = (members.data?.length ?? 0) > 1;

  async function handleDeleteSpace() {
    setDeleteError(null);
    try {
      await deleteSpace.mutateAsync({ id: space.id, force: needsForce && forceConfirmed });
      setConfirmingDelete(false);
    } catch (err) {
      // Не закрываем диалог — реальный частый случай: спейс не пустой,
      // сервер отказывает с понятным сообщением (routers/spaces.py::
      // delete_space) — тогда предлагаем force вместо простого отказа.
      setDeleteError(err instanceof ApiError ? err.message : "Не удалось удалить спейс");
      if (err instanceof ApiError && err.status === 400) setNeedsForce(true);
    }
  }

  return (
    <div className="mb-3">
      <div className="flex items-center gap-0.5">
        <button
          onClick={onToggleCollapse}
          className="flex min-w-0 flex-1 items-center gap-1 rounded px-1 py-1 text-left text-sm font-semibold text-primary hover:bg-muted-hover"
        >
          <span
            className={`inline-block w-3 shrink-0 text-subtle transition-transform ${collapsed ? "" : "rotate-90"}`}
          >
            &#9656;
          </span>
          {space.is_vault && (
            <Lock size={12} className={`shrink-0 ${unlocked ? "text-warning" : "text-subtle"}`} />
          )}
          {isShared && (
            <span title="Общий спейс — несколько участников" className="flex shrink-0 items-center text-subtle">
              <Users size={12} />
            </span>
          )}
          {space.is_public_pages && (
            <span title="Публичные страницы" className="flex shrink-0 items-center text-subtle">
              <Globe size={12} />
            </span>
          )}
          <span className="truncate">{space.name}</span>
        </button>
        {/* Раньше тут был ряд из до пяти отдельных кнопок подряд —
            реальная жалоба: занимало слишком много места на строку
            спейса. Один "⋮" + выпадающий список, тот же паттерн, что и
            UserMenu.tsx. */}
        <div className="relative shrink-0">
          <button
            title="Действия со спейсом"
            onClick={() => setMenuOpen((v) => !v)}
            className="flex h-6 w-6 items-center justify-center text-subtle hover:text-secondary"
          >
            <MoreVertical size={13} />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-20" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-full z-30 w-52 rounded border bg-surface py-1 shadow-lg">
                {space.is_vault && unlocked && (
                  <button
                    onClick={() => {
                      lockVault(space.id);
                      setMenuOpen(false);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-warning hover:bg-warning/10"
                  >
                    <LockOpen size={14} /> Закрыть сейф
                  </button>
                )}
                {space.is_vault && (
                  <button
                    onClick={() => {
                      setChangingPassword(true);
                      setMenuOpen(false);
                    }}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-secondary hover:bg-muted-hover"
                  >
                    <KeyRound size={14} /> Сменить пароль сейфа
                  </button>
                )}
                <button
                  onClick={() => {
                    setManagingMembers(true);
                    setMenuOpen(false);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-secondary hover:bg-muted-hover"
                >
                  <Users size={14} /> Участники спейса
                </button>
                <button
                  onClick={() => {
                    setRenaming(true);
                    setMenuOpen(false);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-secondary hover:bg-muted-hover"
                >
                  <Pencil size={14} /> Переименовать спейс
                </button>
                <button
                  onClick={() => {
                    setDeleteError(null);
                    setNeedsForce(false);
                    setForceConfirmed(false);
                    setConfirmingDelete(true);
                    setMenuOpen(false);
                  }}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm text-danger hover:bg-danger/10"
                >
                  <Trash2 size={14} /> Удалить спейс
                </button>
              </div>
            </>
          )}
        </div>
      </div>
      {/* Реальная жалоба: раньше это была условная РАЗМОНТИРОВКА
          (`{!collapsed && <FolderTree .../>}`) — сворачивание/разворачивание
          выглядело как рывок, а не плавное схлопывание, и каждый повторный
          разворот пересоздавал FolderTree с нуля. grid-template-rows-трюк
          (0fr/1fr + overflow-hidden на вложенном div) анимирует высоту "до
          auto" средствами CSS, а не JS-измерением, и не размонтирует
          содержимое — оно просто визуально скрыто, пока свёрнуто. */}
      <div
        className="ml-3 grid"
        style={{ gridTemplateRows: collapsed ? "0fr" : "1fr", transition: "grid-template-rows 200ms ease-out" }}
      >
        <div className="overflow-hidden">
          {space.is_vault && !unlocked && <VaultUnlockOverlay spaceId={space.id} spaceName={space.name} compact />}
          {(!space.is_vault || unlocked) && (
            <FolderTree
              spaceId={space.id}
              selectedFolderId={isActive ? activeFolderId : undefined}
              onSelect={(folderId) => onSelectFolder(space.id, folderId)}
              isVault={space.is_vault}
            />
          )}
        </div>
      </div>

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

      {confirmingDelete && (
        // Не ConfirmDialog — нужно показать серверную ошибку ("в спейсе
        // есть заметки/папки"), не закрывая диалог, а общий ConfirmDialog
        // такого не умеет.
        <div
          className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setConfirmingDelete(false)}
        >
          <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-lg bg-surface p-4 shadow-xl">
            <div className="mb-1 text-sm text-primary">Удалить спейс «{space.name}»?</div>
            <p className="mb-3 text-xs text-subtle">Можно удалить только пустой спейс — без заметок, списков и папок.</p>
            {deleteError && <div className="mb-2 text-xs text-danger">{deleteError}</div>}
            {needsForce && (
              // Отдельный чекбокс, не автоматический retry — по прямой
              // просьбе: "чтобы вот прям никак не получилось что
              // пользователь нечаянно удалил". Удаление вместе с
              // содержимым необратимо (файлы стираются с диска, а не
              // просто из корзины) — второй явный шаг обязателен.
              <label className="mb-3 flex items-start gap-2 rounded border border-danger/30 bg-danger/10 p-2 text-xs text-danger">
                <input
                  type="checkbox"
                  checked={forceConfirmed}
                  onChange={(e) => setForceConfirmed(e.target.checked)}
                  className="mt-0.5"
                />
                <span>Удалить безвозвратно вместе со всеми заметками, списками, вложениями и папками внутри</span>
              </label>
            )}
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmingDelete(false)}
                className="rounded px-3 py-1.5 text-sm text-subtle hover:bg-muted-hover"
              >
                Отмена
              </button>
              <button
                onClick={handleDeleteSpace}
                disabled={deleteSpace.isPending || (needsForce && !forceConfirmed)}
                className="rounded bg-danger px-3 py-1.5 text-sm text-white hover:bg-danger/90 disabled:opacity-50"
              >
                {deleteSpace.isPending ? "Удаляем…" : "Удалить"}
              </button>
            </div>
          </div>
        </div>
      )}

      {changingPassword && (
        <VaultChangePasswordModal
          spaceId={space.id}
          spaceName={space.name}
          onClose={() => setChangingPassword(false)}
        />
      )}

      {managingMembers && (
        <SpaceMembersModal spaceId={space.id} spaceName={space.name} onClose={() => setManagingMembers(false)} />
      )}
    </div>
  );
}

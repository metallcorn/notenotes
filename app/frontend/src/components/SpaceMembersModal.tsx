import { FormEvent, useState } from "react";
import { Copy, Link2, Users, X } from "lucide-react";
import {
  useAddSpaceMember,
  useCreateSpaceInvite,
  useMe,
  useRemoveSpaceMember,
  useRevokeSpaceInvite,
  useSpaceInvites,
  useSpaceMembers,
} from "../api/hooks";
import Spinner from "./Spinner";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric" });
}

// Управление участниками спейса — по нику (прямое добавление, без
// подтверждения приглашённым: маленький круг доверия, регистрация и так
// уже требует инвайт-код) и по ссылке (токен + явный accept на стороне
// приглашённого — см. routers/spaces.py и /invites/:token).
export default function SpaceMembersModal({
  spaceId,
  spaceName,
  onClose,
}: {
  spaceId: string;
  spaceName: string;
  onClose: () => void;
}) {
  const { data: me } = useMe();
  const { data: members } = useSpaceMembers(spaceId);
  const { data: invites } = useSpaceInvites(spaceId);
  const addMember = useAddSpaceMember(spaceId);
  const removeMember = useRemoveSpaceMember(spaceId);
  const createInvite = useCreateSpaceInvite(spaceId);
  const revokeInvite = useRevokeSpaceInvite(spaceId);

  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const [copiedId, setCopiedId] = useState<string | null>(null);

  async function onAddSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    const value = username.trim();
    if (!value) return;
    try {
      await addMember.mutateAsync(value);
      setUsername("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Не удалось добавить участника");
    }
  }

  function inviteLink(token: string): string {
    return `${window.location.origin}/invites/${token}`;
  }

  async function copyInviteLink(id: string, token: string) {
    try {
      await navigator.clipboard.writeText(inviteLink(token));
      setCopiedId(id);
      setTimeout(() => setCopiedId((cur) => (cur === id ? null : cur)), 1500);
    } catch {
      // буфер обмена недоступен — молча игнорируем, ссылку всё ещё можно
      // скопировать вручную из текста рядом.
    }
  }

  return (
    <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[80vh] w-full max-w-sm flex-col rounded-lg bg-surface p-4 shadow-xl"
      >
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-sm font-medium text-primary">
            <Users size={14} /> Участники «{spaceName}»
          </div>
          <button onClick={onClose} className="text-subtle hover:text-secondary">
            <X size={16} />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          <div>
            <div className="mb-1.5 text-xs font-medium uppercase tracking-wide text-subtle">Участники</div>
            <div className="space-y-1">
              {(members ?? []).map((m) => (
                <div key={m.user_id} className="flex items-center justify-between gap-2 rounded px-1.5 py-1 text-sm">
                  <div className="min-w-0">
                    <div className="truncate text-primary">{m.name}</div>
                    <div className="truncate text-xs text-subtle">@{m.username}</div>
                  </div>
                  <button
                    title={m.user_id === me?.id ? "Покинуть спейс" : "Убрать участника"}
                    onClick={() => removeMember.mutate(m.user_id)}
                    className="shrink-0 text-xs text-subtle hover:text-danger"
                  >
                    {m.user_id === me?.id ? "Выйти" : "Убрать"}
                  </button>
                </div>
              ))}
            </div>
            <form onSubmit={onAddSubmit} className="mt-2 flex gap-1.5">
              <input
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Ник пользователя"
                disabled={addMember.isPending}
                className="min-w-0 flex-1 rounded border px-2.5 py-1.5 text-sm disabled:opacity-50"
              />
              <button
                type="submit"
                disabled={addMember.isPending || !username.trim()}
                className="flex shrink-0 items-center gap-1 rounded bg-accent px-2.5 py-1.5 text-sm text-white disabled:opacity-50"
              >
                {addMember.isPending && <Spinner size={12} />}
                Добавить
              </button>
            </form>
            {error && <div className="mt-1 text-xs text-danger">{error}</div>}
          </div>

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wide text-subtle">Ссылки-приглашения</span>
              <button
                onClick={() => createInvite.mutate()}
                disabled={createInvite.isPending}
                className="flex items-center gap-1 text-xs text-subtle hover:text-primary disabled:opacity-50"
              >
                {createInvite.isPending ? <Spinner size={11} /> : <Link2 size={11} />}
                Создать
              </button>
            </div>
            <div className="space-y-1">
              {(invites ?? []).length === 0 && (
                <div className="text-xs text-subtle">Активных ссылок нет</div>
              )}
              {(invites ?? []).map((inv) => (
                <div key={inv.id} className="flex items-center justify-between gap-2 rounded px-1.5 py-1 text-sm">
                  <div className="min-w-0">
                    <div className="truncate font-mono text-xs text-secondary">{inv.token.slice(0, 16)}…</div>
                    <div className="text-xs text-subtle">до {formatDate(inv.expires_at)}</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      title="Скопировать ссылку"
                      onClick={() => copyInviteLink(inv.id, inv.token)}
                      className="flex h-6 w-6 items-center justify-center text-subtle hover:text-secondary"
                    >
                      <Copy size={12} />
                    </button>
                    <button
                      title="Отозвать"
                      onClick={() => revokeInvite.mutate(inv.id)}
                      className="text-xs text-subtle hover:text-danger"
                    >
                      Отозвать
                    </button>
                  </div>
                  {copiedId === inv.id && <span className="text-xs text-success">Скопировано</span>}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

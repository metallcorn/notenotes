import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Link2 } from "lucide-react";
import { useAcceptSpaceInvite } from "../api/hooks";
import { ApiError } from "../api/client";
import Spinner from "../components/Spinner";

// Приём ссылки-приглашения в спейс — залогиненный пользователь сюда
// приходит по /invites/:token (SpaceMembersModal.tsx копирует такую
// ссылку). RequireAuth (App.tsx) уже гарантирует, что дошли только
// авторизованные — accept вызывается сразу, без лишнего клика.
export default function InviteAcceptPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const accept = useAcceptSpaceInvite();
  const [error, setError] = useState<string | null>(null);
  const [spaceName, setSpaceName] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    accept
      .mutateAsync(token)
      .then((space) => setSpaceName(space.name))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Не удалось принять приглашение"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  return (
    <div className="flex min-h-dvh items-center justify-center bg-muted p-4">
      <div className="w-full max-w-sm rounded-lg bg-surface p-5 text-center shadow-sm">
        <Link2 size={20} className="mx-auto mb-2 text-subtle" />
        {accept.isPending && (
          <div className="flex items-center justify-center gap-2 text-sm text-subtle">
            <Spinner size={14} /> Принимаем приглашение…
          </div>
        )}
        {error && <div className="text-sm text-danger">{error}</div>}
        {spaceName && (
          <>
            <div className="mb-3 text-sm text-secondary">
              Вы вступили в спейс «{spaceName}»
            </div>
            <button
              onClick={() => navigate("/")}
              className="rounded bg-accent px-4 py-2 text-sm text-white hover:bg-accent/90"
            >
              Перейти в Notenotes
            </button>
          </>
        )}
      </div>
    </div>
  );
}

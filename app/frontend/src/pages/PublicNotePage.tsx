import { FormEvent, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Lock, FileText } from "lucide-react";
import { ApiError, api } from "../api/client";
import PublicNoteView from "../components/PublicNoteView";
import Spinner from "../components/Spinner";

interface PublicNote {
  title: string;
  content: string;
  updated_at: string;
}

// Ссылки на вложения в content — "/api/uploads/{id}", как у обычных
// заметок (см. app/frontend/src/api/hooks.ts, UPLOAD_URL_RE и
// decryptUploadUrlsInContent — тот же приём для сейфа: подмена ссылок
// прямо в тексте content ДО того, как он попадёт в редактор). Анониму
// обычный /api/uploads/{id} отдаст 401 — переписываем на анонимный путь,
// который проверяет валидность самого токена шаринга, не сессию.
function rewriteUploadUrls(content: string, token: string): string {
  return content.replace(/\/api\/uploads\/([0-9a-f-]{36})/gi, (_match, id) => `/api/public/${token}/uploads/${id}`);
}

type ViewState =
  | { kind: "loading" }
  | { kind: "password" }
  | { kind: "ready"; note: PublicNote }
  | { kind: "error"; message: string };

export default function PublicNotePage() {
  const { token } = useParams<{ token: string }>();
  const [state, setState] = useState<ViewState>({ kind: "loading" });
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [unlocking, setUnlocking] = useState(false);

  useEffect(() => {
    if (!token) return;
    api
      .get<PublicNote | { requires_password: true }>(`/public/${token}`)
      .then((data) => {
        if ("requires_password" in data) {
          setState({ kind: "password" });
        } else {
          setState({ kind: "ready", note: data });
        }
      })
      .catch((err) => {
        setState({ kind: "error", message: err instanceof ApiError ? err.message : "Страница не найдена" });
      });
  }, [token]);

  async function onSubmitPassword(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setPasswordError(null);
    setUnlocking(true);
    try {
      const note = await api.post<PublicNote>(`/public/${token}/unlock`, { password });
      setState({ kind: "ready", note });
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : "Не удалось открыть страницу");
    } finally {
      setUnlocking(false);
    }
  }

  return (
    <div className="min-h-dvh bg-muted">
      <div className="mx-auto max-w-3xl px-4 py-10">
        {state.kind === "loading" && (
          <div className="flex items-center justify-center gap-2 py-20 text-subtle">
            <Spinner size={16} /> Загрузка…
          </div>
        )}

        {state.kind === "error" && (
          <div className="rounded-lg border bg-surface p-8 text-center text-sm text-subtle">{state.message}</div>
        )}

        {state.kind === "password" && (
          <form
            onSubmit={onSubmitPassword}
            className="mx-auto mt-16 w-full max-w-sm rounded-lg border bg-surface p-5 shadow-sm"
          >
            <div className="mb-3 flex items-center gap-1.5 text-sm font-medium text-primary">
              <Lock size={14} /> Страница защищена паролем
            </div>
            <input
              autoFocus
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Пароль"
              disabled={unlocking}
              className="mb-2 w-full rounded border px-3 py-2 text-sm disabled:opacity-50"
            />
            {passwordError && <div className="mb-2 text-xs text-danger">{passwordError}</div>}
            <button
              type="submit"
              disabled={unlocking || !password}
              className="flex w-full items-center justify-center gap-1.5 rounded bg-accent px-3 py-2 text-sm text-on-accent disabled:opacity-50"
            >
              {unlocking && <Spinner size={12} />}
              Открыть
            </button>
          </form>
        )}

        {state.kind === "ready" && token && (
          <div className="rounded-lg border bg-surface p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2 border-b pb-4">
              <FileText size={16} className="shrink-0 text-subtle" />
              <h1 className="min-w-0 flex-1 truncate text-lg font-semibold text-primary">
                {state.note.title || "Без названия"}
              </h1>
            </div>
            <PublicNoteView content={rewriteUploadUrls(state.note.content, token)} token={token!} />
          </div>
        )}
      </div>
    </div>
  );
}

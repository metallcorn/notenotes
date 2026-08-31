import { useState } from "react";
import { Copy, Globe, X } from "lucide-react";
import { useItemShareInfo, useShareItem, useUnshareItem } from "../api/hooks";
import Spinner from "./Spinner";

// Управление публикацией заметки (routers/public.py) — доступно только
// для заметок в спейсе «Публичные страницы» (см. NoteEditor.tsx, кнопка
// показывается только там). По образцу SpaceMembersModal.tsx.
export default function ShareNoteModal({ itemId, onClose }: { itemId: string; onClose: () => void }) {
  const { data: info } = useItemShareInfo(itemId);
  const shareItem = useShareItem(itemId);
  const unshareItem = useUnshareItem(itemId);

  const [password, setPassword] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<string>("");
  const [singleUse, setSingleUse] = useState(false);
  const [copied, setCopied] = useState(false);

  const shareUrl = info?.share_token ? `${window.location.origin}/s/${info.share_token}` : null;

  async function onPublish() {
    await shareItem.mutateAsync({
      password: password.trim() || undefined,
      expires_in_days: expiresInDays ? Number(expiresInDays) : undefined,
      single_use: singleUse,
    });
    setPassword("");
  }

  async function copyLink() {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // буфер обмена недоступен — молча игнорируем, ссылку видно и так.
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-lg bg-surface p-4 shadow-xl"
      >
        <div className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-sm font-medium text-primary">
            <Globe size={14} /> Публичная ссылка
          </div>
          <button onClick={onClose} className="text-subtle hover:text-secondary">
            <X size={16} />
          </button>
        </div>

        {info?.is_public && shareUrl ? (
          <div className="space-y-3">
            <div className="flex items-center gap-1.5 rounded border bg-muted px-2.5 py-2 text-xs text-secondary">
              <span className="min-w-0 flex-1 truncate font-mono">{shareUrl}</span>
              <button onClick={copyLink} className="shrink-0 text-subtle hover:text-secondary" title="Скопировать">
                <Copy size={13} />
              </button>
            </div>
            {copied && <div className="text-xs text-success">Скопировано</div>}
            <div className="space-y-0.5 text-xs text-subtle">
              {info.has_password && <div>Защищена паролем</div>}
              {info.share_expires_at && <div>Истекает: {new Date(info.share_expires_at).toLocaleDateString("ru-RU")}</div>}
              {info.share_single_use && <div>{info.share_used_at ? "Уже открывалась (одноразовая)" : "Одноразовая ссылка"}</div>}
              {!info.has_password && !info.share_expires_at && !info.share_single_use && <div>Без пароля, бессрочная</div>}
            </div>
            <button
              onClick={() => unshareItem.mutate()}
              disabled={unshareItem.isPending}
              className="w-full rounded border px-3 py-1.5 text-sm text-danger hover:bg-danger/10 disabled:opacity-50"
            >
              {unshareItem.isPending ? "Снимаем…" : "Прекратить публикацию"}
            </button>
          </div>
        ) : (
          <div className="space-y-2.5">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Пароль (необязательно)"
              disabled={shareItem.isPending}
              className="w-full rounded border px-2.5 py-1.5 text-sm disabled:opacity-50"
            />
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={365}
                value={expiresInDays}
                onChange={(e) => setExpiresInDays(e.target.value)}
                placeholder="Срок в днях"
                disabled={shareItem.isPending}
                className="w-28 rounded border px-2.5 py-1.5 text-sm disabled:opacity-50"
              />
              <span className="text-xs text-subtle">пусто — до отмены</span>
            </div>
            <label className="flex items-center gap-1.5 text-xs text-secondary">
              <input type="checkbox" checked={singleUse} onChange={(e) => setSingleUse(e.target.checked)} />
              Одноразовая ссылка
            </label>
            <button
              onClick={onPublish}
              disabled={shareItem.isPending}
              className="flex w-full items-center justify-center gap-1.5 rounded bg-accent px-3 py-2 text-sm text-white disabled:opacity-50"
            >
              {shareItem.isPending && <Spinner size={12} />}
              Опубликовать
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

import { useState } from "react";
import { Copy, Globe, X } from "lucide-react";
import { useItemShareInfo, useShareItem, useUnshareItem } from "../api/hooks";
import Spinner from "./Spinner";
import { dateLocale } from "../i18n";

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
    <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-3xl bg-surface p-4 shadow-xl"
      >
        <div className="mb-1 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-2xl font-extrabold tracking-tight text-primary">
            <Globe size={20} /> Поделиться
          </h2>
          <button onClick={onClose} aria-label="Закрыть" className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-primary hover:bg-muted-hover">
            <X size={18} />
          </button>
        </div>
        <div className="mb-3 text-sm font-semibold text-subtle">
          {info?.is_public
            ? "Открыть может любой, у кого есть ссылка — без входа, только чтение."
            : "Ссылка выключена — заметку видят только участники спейса."}
        </div>

        {info?.is_public && shareUrl ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2 rounded-2xl bg-muted py-1.5 pl-4 pr-1.5 text-sm font-bold text-primary">
              <span className="min-w-0 flex-1 truncate">{shareUrl.replace(/^https?:\/\//, "")}</span>
              <button
                onClick={copyLink}
                className="flex h-10 shrink-0 items-center gap-1.5 rounded-xl bg-accent px-3.5 text-sm font-extrabold text-on-accent"
                title="Скопировать"
              >
                <Copy size={14} /> {copied ? "Готово" : "Копировать"}
              </button>
            </div>
            <div className="space-y-0.5 text-xs font-semibold text-subtle">
              {info.has_password && <div>Защищена паролем</div>}
              {info.share_expires_at && <div>Истекает: {new Date(info.share_expires_at).toLocaleDateString(dateLocale)}</div>}
              {info.share_single_use && <div>{info.share_used_at ? "Уже открывалась (одноразовая)" : "Одноразовая ссылка"}</div>}
              {!info.has_password && !info.share_expires_at && !info.share_single_use && <div>Без пароля, бессрочная</div>}
            </div>
            <button
              onClick={() => unshareItem.mutate()}
              disabled={unshareItem.isPending}
              className="h-11 w-full rounded-2xl bg-danger-soft text-sm font-extrabold text-danger disabled:opacity-50"
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
              className="h-11 w-full rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40 disabled:opacity-50"
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
                className="h-11 w-28 rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40 disabled:opacity-50"
              />
              <span className="text-xs text-subtle">пусто — до отмены</span>
            </div>
            <label className="flex min-h-10 items-center gap-2 text-sm font-semibold text-secondary">
              <input type="checkbox" checked={singleUse} onChange={(e) => setSingleUse(e.target.checked)} />
              Одноразовая ссылка
            </label>
            <button
              onClick={onPublish}
              disabled={shareItem.isPending}
              className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-accent px-3 text-[15px] font-extrabold text-on-accent disabled:opacity-50"
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

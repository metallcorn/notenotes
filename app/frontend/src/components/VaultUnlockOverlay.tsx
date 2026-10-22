import { FormEvent, useState } from "react";
import { Lock } from "lucide-react";
import { useVaultUnlockInfo } from "../api/hooks";
import type { EncryptedField } from "../lib/vaultCrypto";
import { checkVerifier, deriveKey } from "../lib/vaultCrypto";
import { unlockVault } from "../lib/vaultSession";
import Spinner from "./Spinner";
import { t } from "../i18n";

// Разблокировка сейфа: пароль никогда не покидает браузер и не шлётся на
// сервер для проверки (zero-knowledge, см. vaultCrypto.ts) — единственный
// сетевой запрос здесь получает уже сохранённые соль/verifier, дальше всё
// целиком локально.
export default function VaultUnlockOverlay({
  spaceId,
  spaceName,
  compact = false,
}: {
  spaceId: string;
  spaceName: string;
  compact?: boolean;
}) {
  const { data: info, isLoading } = useVaultUnlockInfo(spaceId);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!info) return;
    setError("");
    setChecking(true);
    try {
      const key = await deriveKey(password, info.vault_salt);
      const verifier = JSON.parse(info.vault_verifier) as EncryptedField;
      const ok = await checkVerifier(key, verifier);
      if (!ok) {
        setError("Неверный пароль");
        return;
      }
      unlockVault(spaceId, key);
      setPassword("");
    } finally {
      setChecking(false);
    }
  }

  return (
    // Полный экран — тёмная карточка с замком (макет «Сейф закрыт», 21.10);
    // compact — короткая форма внутри карточки спейса в сайдбаре.
    <div
      className={`flex flex-col items-center gap-2 ${
        compact ? "p-2 text-nav-text" : "m-3 flex-1 justify-between gap-3 rounded-3xl bg-nav px-6 pb-5 pt-10 text-nav-text lg:m-6 lg:justify-center"
      }`}
    >
      {!compact && (
        <span
          className="flex h-28 w-28 items-center justify-center rounded-[36px] bg-white/10 text-lime"
          style={{ boxShadow: "0 0 60px rgba(212,242,90,0.15)" }}
        >
          <Lock size={48} strokeWidth={2} />
        </span>
      )}
      <div className={`text-center ${compact ? "text-xs font-semibold text-nav-muted" : "text-[30px] font-extrabold tracking-tight"}`}>
        {compact ? "Заблокировано" : spaceName || t("vault.title")}
      </div>
      {!compact && (
        <div className="max-w-xs text-center text-[15px] font-medium leading-snug text-nav-muted">{t("vault.lockedText")}</div>
      )}
      {isLoading ? (
        <Spinner size={compact ? 12 : 16} />
      ) : (
        <form onSubmit={onSubmit} className={`flex w-full max-w-xs flex-col gap-2 ${compact ? "" : "mt-4"}`}>
          {!compact && <span className="text-[13px] font-bold text-nav-muted">{t("vault.password")}</span>}
          <input
            autoFocus
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={compact ? "Пароль" : ""}
            aria-label={t("vault.password")}
            className={`w-full rounded-2xl bg-white/10 px-4 text-nav-text outline-none placeholder:text-nav-muted focus:ring-2 focus:ring-lime/60 ${
              compact ? "h-10 border-0 text-sm" : "h-14 border-2 border-lime text-lg tracking-[0.2em]"
            }`}
          />
          {error && <div className="text-xs font-bold text-lime">{error}</div>}
          <button
            type="submit"
            disabled={checking || !password}
            className={`flex items-center justify-center gap-1.5 rounded-2xl bg-lime font-extrabold text-on-lime disabled:opacity-50 ${
              compact ? "h-10 text-sm" : "mt-1 h-14 text-base"
            }`}
          >
            {checking && <Spinner size={12} />}
            {compact ? "Разблокировать" : t("vault.open")}
          </button>
          {!compact && <div className="mt-2 text-center text-[13px] font-semibold text-nav-muted">{t("vault.autoLock")}</div>}
        </form>
      )}
      {!compact && (
        <div className="mt-6 w-full rounded-2xl bg-white/5 px-3.5 py-3 text-xs font-semibold leading-snug text-nav-muted">{t("vault.forgot")}</div>
      )}
    </div>
  );
}

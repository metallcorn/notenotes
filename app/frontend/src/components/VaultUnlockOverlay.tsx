import { FormEvent, useState } from "react";
import { Lock } from "lucide-react";
import { useVaultUnlockInfo } from "../api/hooks";
import type { EncryptedField } from "../lib/vaultCrypto";
import { checkVerifier, deriveKey } from "../lib/vaultCrypto";
import { unlockVault } from "../lib/vaultSession";
import Spinner from "./Spinner";

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
        compact ? "p-2 text-nav-text" : "m-3 justify-center gap-3 rounded-3xl bg-nav p-6 text-nav-text lg:m-6"
      }`}
    >
      {!compact && (
        <span className="flex h-16 w-16 items-center justify-center rounded-3xl bg-white/10 text-lime">
          <Lock size={28} />
        </span>
      )}
      <div className={`text-center ${compact ? "text-xs font-semibold text-nav-muted" : "text-xl font-extrabold tracking-tight"}`}>
        {compact ? "Заблокировано" : `Сейф «${spaceName}» закрыт`}
      </div>
      {!compact && (
        <div className="text-center text-sm font-semibold text-nav-muted">Пароль не покидает это устройство</div>
      )}
      {isLoading ? (
        <Spinner size={compact ? 12 : 16} />
      ) : (
        <form onSubmit={onSubmit} className="flex w-full max-w-xs flex-col gap-2">
          <input
            autoFocus
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль"
            className={`w-full rounded-2xl border-0 bg-white/10 px-4 text-nav-text outline-none placeholder:text-nav-muted focus:ring-2 focus:ring-lime/60 ${
              compact ? "h-10 text-sm" : "h-12 text-[15px]"
            }`}
          />
          {error && <div className="text-xs font-bold text-lime">{error}</div>}
          <button
            type="submit"
            disabled={checking || !password}
            className={`flex items-center justify-center gap-1.5 rounded-2xl bg-lime font-extrabold text-on-lime disabled:opacity-50 ${
              compact ? "h-10 text-sm" : "h-12 text-[15px]"
            }`}
          >
            {checking && <Spinner size={12} />}
            Разблокировать
          </button>
        </form>
      )}
    </div>
  );
}

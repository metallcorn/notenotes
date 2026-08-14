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
    <div className={`flex flex-col items-center gap-2 ${compact ? "p-3" : "h-full justify-center gap-3 p-6"}`}>
      {!compact && <Lock size={24} className="text-slate-400" />}
      <div className={`text-center font-medium text-slate-700 ${compact ? "text-xs" : "text-sm"}`}>
        {compact ? "Заблокировано" : `Сейф «${spaceName}» заблокирован`}
      </div>
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
            className="w-full rounded border px-2 py-1.5 text-sm"
          />
          {error && <div className="text-xs text-red-600">{error}</div>}
          <button
            type="submit"
            disabled={checking || !password}
            className="flex items-center justify-center gap-1.5 rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {checking && <Spinner size={12} />}
            Разблокировать
          </button>
        </form>
      )}
    </div>
  );
}

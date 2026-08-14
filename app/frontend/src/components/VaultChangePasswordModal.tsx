import { FormEvent, useState } from "react";
import { KeyRound } from "lucide-react";
import { useRotateVaultPassword, useVaultUnlockInfo } from "../api/hooks";
import type { EncryptedField } from "../lib/vaultCrypto";
import { checkVerifier, deriveKey } from "../lib/vaultCrypto";
import Spinner from "./Spinner";

// Смена пароля сейфа — три поля, как и попросили: текущий пароль (для
// расшифровки всего существующего содержимого и как обычная re-auth
// проверка перед разрушительной операцией), новый дважды. Реальная работа
// (перешифровка всех заметок и файлов) — useRotateVaultPassword,
// api/hooks.ts.
export default function VaultChangePasswordModal({
  spaceId,
  spaceName,
  onClose,
}: {
  spaceId: string;
  spaceName: string;
  onClose: () => void;
}) {
  const { data: info } = useVaultUnlockInfo(spaceId);
  const rotate = useRotateVaultPassword();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newPassword2, setNewPassword2] = useState("");
  const [error, setError] = useState("");
  const [checking, setChecking] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (!info) return;
    if (newPassword.length < 8) {
      setError("Новый пароль должен быть не короче 8 символов");
      return;
    }
    if (newPassword !== newPassword2) {
      setError("Новые пароли не совпадают");
      return;
    }
    setChecking(true);
    try {
      const currentKey = await deriveKey(currentPassword, info.vault_salt);
      const verifier = JSON.parse(info.vault_verifier) as EncryptedField;
      const ok = await checkVerifier(currentKey, verifier);
      if (!ok) {
        setError("Текущий пароль неверный");
        return;
      }
      await rotate.mutateAsync({ spaceId, oldKey: currentKey, newPassword });
      onClose();
    } catch {
      setError("Не удалось сменить пароль — попробуйте ещё раз");
    } finally {
      setChecking(false);
    }
  }

  const busy = checking || rotate.isPending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={busy ? undefined : onClose}>
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-lg bg-white p-4 shadow-xl"
      >
        <div className="mb-1 flex items-center gap-1.5 text-sm font-medium text-slate-900">
          <KeyRound size={14} /> Сменить пароль сейфа «{spaceName}»
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Все заметки и файлы в сейфе будут перешифрованы новым паролем. Если файлов много, это займёт
          время — не закрывайте вкладку, пока идёт смена.
        </p>
        <input
          autoFocus
          type="password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          placeholder="Текущий пароль"
          disabled={busy}
          className="mb-2 w-full rounded border px-3 py-2 text-sm disabled:opacity-50"
        />
        <input
          type="password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          placeholder="Новый пароль"
          disabled={busy}
          className="mb-2 w-full rounded border px-3 py-2 text-sm disabled:opacity-50"
        />
        <input
          type="password"
          value={newPassword2}
          onChange={(e) => setNewPassword2(e.target.value)}
          placeholder="Повторите новый пароль"
          disabled={busy}
          className="w-full rounded border px-3 py-2 text-sm disabled:opacity-50"
        />
        {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100 disabled:opacity-50"
          >
            Отмена
          </button>
          <button
            type="submit"
            disabled={busy}
            className="flex items-center gap-1.5 rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
          >
            {busy && <Spinner size={12} />}
            {busy ? "Меняем…" : "Сменить пароль"}
          </button>
        </div>
      </form>
    </div>
  );
}

import { FormEvent, useState } from "react";
import { Lock } from "lucide-react";
import { useCreateSpace } from "../api/hooks";
import { createVerifier, deriveKey, generateSalt } from "../lib/vaultCrypto";
import { unlockVault } from "../lib/vaultSession";
import Spinner from "./Spinner";

export default function CreateSpaceButton({ onCreated }: { onCreated: (spaceId: string) => void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [isVault, setIsVault] = useState(false);
  const [step, setStep] = useState<"name" | "password">("name");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState("");
  const createSpace = useCreateSpace();

  function reset() {
    setAdding(false);
    setName("");
    setIsVault(false);
    setStep("name");
    setPassword("");
    setPassword2("");
    setError("");
  }

  async function submitFirstStep(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    if (isVault) {
      setStep("password");
      return;
    }
    const space = await createSpace.mutateAsync({ name: name.trim() });
    reset();
    onCreated(space.id);
  }

  async function submitVaultPassword(e: FormEvent) {
    e.preventDefault();
    setError("");
    if (password.length < 8) {
      setError("Пароль должен быть не короче 8 символов");
      return;
    }
    if (password !== password2) {
      setError("Пароли не совпадают");
      return;
    }
    // Соль/verifier считаются здесь, до запроса — сервер только хранит их,
    // сам пароль на сервер никогда не уходит (zero-knowledge, см. vaultCrypto.ts).
    const salt = generateSalt();
    const key = await deriveKey(password, salt);
    const verifier = await createVerifier(key);
    const space = await createSpace.mutateAsync({
      name: name.trim(),
      is_vault: true,
      vault_salt: salt,
      vault_verifier: JSON.stringify(verifier),
    });
    unlockVault(space.id, key);
    reset();
    onCreated(space.id);
  }

  if (!adding) {
    return (
      <button onClick={() => setAdding(true)} className="text-xs text-slate-400 hover:text-slate-700">
        + спейс
      </button>
    );
  }

  if (step === "password") {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={reset}>
        <form
          onClick={(e) => e.stopPropagation()}
          onSubmit={submitVaultPassword}
          className="w-full max-w-sm rounded-lg bg-white p-4 shadow-xl"
        >
          <div className="mb-1 flex items-center gap-1.5 text-sm font-medium text-slate-900">
            <Lock size={14} /> Пароль сейфа «{name.trim()}»
          </div>
          <p className="mb-3 text-xs text-slate-500">
            Пароль нигде не хранится и не передаётся на сервер. При утере доступ к содержимому
            сейфа восстановить нельзя — единственный выход тогда — удалить сейф целиком.
          </p>
          <input
            autoFocus
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль"
            className="mb-2 w-full rounded border px-3 py-2 text-sm"
          />
          <input
            type="password"
            value={password2}
            onChange={(e) => setPassword2(e.target.value)}
            placeholder="Повторите пароль"
            className="w-full rounded border px-3 py-2 text-sm"
          />
          {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={reset}
              className="rounded px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={createSpace.isPending}
              className="flex items-center gap-1.5 rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {createSpace.isPending && <Spinner size={12} />}
              Создать сейф
            </button>
          </div>
        </form>
      </div>
    );
  }

  return (
    <form onSubmit={submitFirstStep} className="flex items-center gap-1">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => !name.trim() && setAdding(false)}
        placeholder="Название"
        className="w-24 rounded border px-1.5 py-0.5 text-xs"
      />
      <button
        type="button"
        title={isVault ? "Сейф — зашифрован, без ИИ" : "Сделать сейфом"}
        onClick={() => setIsVault((v) => !v)}
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded ${
          isVault ? "bg-slate-900 text-white" : "text-slate-400 hover:text-slate-700"
        }`}
      >
        <Lock size={12} />
      </button>
      <button
        type="submit"
        disabled={createSpace.isPending}
        className="flex shrink-0 items-center justify-center gap-1 rounded bg-slate-900 px-2 py-0.5 text-xs text-white disabled:opacity-50"
      >
        {createSpace.isPending ? <Spinner size={12} /> : "OK"}
      </button>
    </form>
  );
}

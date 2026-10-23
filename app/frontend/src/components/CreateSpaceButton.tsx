import { FormEvent, useState } from "react";
import { Globe, Lock } from "lucide-react";
import { useCreateSpace } from "../api/hooks";
import { createVerifier, deriveKey, generateSalt } from "../lib/vaultCrypto";
import { unlockVault } from "../lib/vaultSession";
import Spinner from "./Spinner";
import { t } from "../i18n";

// variant "pill" — тёмная кнопка «+ Новый» в шторке «Спейсы» (макет 21.10),
// форма названия открывается карточкой поверх, а не инлайном в строке.
export default function CreateSpaceButton({
  onCreated,
  variant = "inline",
}: {
  onCreated: (spaceId: string) => void;
  variant?: "inline" | "pill";
}) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [isVault, setIsVault] = useState(false);
  // Публичные страницы (routers/public.py) — взаимоисключающе с сейфом,
  // сервер и так это проверит, но незачем позволять выбрать оба в UI.
  const [isPublicPages, setIsPublicPages] = useState(false);
  const [step, setStep] = useState<"name" | "password">("name");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState("");
  const createSpace = useCreateSpace();

  function reset() {
    setAdding(false);
    setName("");
    setIsVault(false);
    setIsPublicPages(false);
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
    const space = await createSpace.mutateAsync({ name: name.trim(), is_public_pages: isPublicPages });
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
    return variant === "pill" ? (
      <button
        onClick={() => setAdding(true)}
        className="h-10 rounded-full bg-accent px-3.5 text-sm font-extrabold text-on-accent"
      >
        {t("spaces.new")}
      </button>
    ) : (
      <button onClick={() => setAdding(true)} className="h-8 rounded-full bg-surface px-3 text-xs font-extrabold text-primary shadow-card hover:bg-muted">
        + спейс
      </button>
    );
  }

  if (step === "password") {
    return (
      <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={reset}>
        <form
          onClick={(e) => e.stopPropagation()}
          onSubmit={submitVaultPassword}
          className="w-full max-w-sm rounded-lg bg-surface p-4 shadow-xl"
        >
          <div className="mb-1 flex items-center gap-1.5 text-sm font-medium text-primary">
            <Lock size={14} /> Пароль сейфа «{name.trim()}»
          </div>
          <p className="mb-3 text-xs text-subtle">
            Пароль нигде не хранится и не передаётся на сервер. При утере доступ к содержимому
            сейфа восстановить нельзя — единственный выход тогда — удалить сейф целиком.
          </p>
          <input
            autoFocus
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Пароль"
            className="mb-2 h-11 w-full rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
          />
          <input
            type="password"
            value={password2}
            onChange={(e) => setPassword2(e.target.value)}
            placeholder="Повторите пароль"
            className="h-11 w-full rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
          />
          {error && <div className="mt-2 text-xs text-danger">{error}</div>}
          <div className="mt-3 flex justify-end gap-2">
            <button
              type="button"
              onClick={reset}
              className="h-10 rounded-xl px-4 text-sm font-bold text-secondary hover:bg-muted"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={createSpace.isPending}
              className="flex items-center gap-1.5 h-10 rounded-xl bg-accent px-4 text-sm font-bold text-on-accent disabled:opacity-50"
            >
              {createSpace.isPending && <Spinner size={12} />}
              Создать сейф
            </button>
          </div>
        </form>
      </div>
    );
  }

  if (variant === "pill") {
    const chip = (active: boolean, label: string, Icon: typeof Lock, onClick: () => void) => (
      <button
        type="button"
        onClick={onClick}
        aria-pressed={active}
        className={`flex h-10 items-center gap-1.5 rounded-full px-3.5 text-sm font-bold ${
          active ? "bg-accent text-on-accent" : "bg-muted text-primary"
        }`}
      >
        <Icon size={14} /> {label}
      </button>
    );
    return (
      <div className="modal-in fixed inset-0 z-[60] flex items-start justify-center bg-black/45 p-3 pt-16 sm:items-center" onClick={reset}>
        <form
          onClick={(e) => e.stopPropagation()}
          onSubmit={submitFirstStep}
          className="w-full max-w-sm rounded-3xl bg-surface p-5 shadow-xl"
        >
          <div className="text-[13px] font-extrabold uppercase tracking-wider text-subtle">Новый спейс</div>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Название"
            className="mt-3 h-[52px] w-full rounded-2xl border-2 border-brand bg-surface px-3.5 text-[17px] font-bold text-primary outline-none placeholder:font-semibold placeholder:text-subtle"
          />
          <div className="mt-3 flex flex-wrap gap-2">
            {chip(isVault, "Сейф", Lock, () => {
              setIsVault((v) => !v);
              setIsPublicPages(false);
            })}
            {chip(isPublicPages, "Публичные страницы", Globe, () => {
              setIsPublicPages((v) => !v);
              setIsVault(false);
            })}
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <button type="button" onClick={reset} className="h-11 rounded-2xl bg-muted px-4 text-[15px] font-bold text-primary">
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={!name.trim() || createSpace.isPending}
              className="flex h-11 items-center gap-2 rounded-2xl bg-accent px-5 text-[15px] font-extrabold text-on-accent disabled:opacity-50"
            >
              {createSpace.isPending && <Spinner size={14} />}
              {isVault ? "Дальше" : t("folders.create")}
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
        className="h-9 w-28 rounded-xl border bg-surface px-2.5 text-xs outline-none focus:ring-2 focus:ring-brand/40"
      />
      <button
        type="button"
        title={isVault ? "Сейф — зашифрован, без ИИ" : "Сделать сейфом"}
        onClick={() => {
          setIsVault((v) => !v);
          setIsPublicPages(false);
        }}
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded ${
          isVault ? "bg-accent text-on-accent" : "text-subtle hover:text-secondary"
        }`}
      >
        <Lock size={12} />
      </button>
      <button
        type="button"
        title={isPublicPages ? "Публичные страницы" : "Сделать спейсом публичных страниц"}
        onClick={() => {
          setIsPublicPages((v) => !v);
          setIsVault(false);
        }}
        className={`flex h-5 w-5 shrink-0 items-center justify-center rounded ${
          isPublicPages ? "bg-accent text-on-accent" : "text-subtle hover:text-secondary"
        }`}
      >
        <Globe size={12} />
      </button>
      <button
        type="submit"
        disabled={createSpace.isPending}
        className="flex shrink-0 items-center justify-center gap-1 rounded bg-accent px-2 py-0.5 text-xs text-on-accent disabled:opacity-50"
      >
        {createSpace.isPending ? <Spinner size={12} /> : "OK"}
      </button>
    </form>
  );
}

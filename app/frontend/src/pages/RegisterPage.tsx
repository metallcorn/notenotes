import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { useRegister } from "../api/hooks";
import { ApiError } from "../api/client";
import Spinner from "../components/Spinner";

export default function RegisterPage() {
  const [name, setName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const register = useRegister();
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    // См. LoginPage — читаем из DOM формы, а не из state, из-за автозаполнения.
    const data = new FormData(e.currentTarget);
    const nameValue = String(data.get("name") ?? "").trim();
    const usernameValue = String(data.get("username") ?? "").trim();
    const passwordValue = String(data.get("password") ?? "").trim();
    const inviteCodeValue = String(data.get("invite_code") ?? "").trim();
    try {
      await register.mutateAsync({
        name: nameValue,
        username: usernameValue,
        password: passwordValue,
        invite_code: inviteCodeValue,
      });
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось зарегистрироваться");
    }
  }

  return (
    <div className="flex min-h-dvh flex-col bg-nav sm:items-center sm:justify-center sm:p-4">
      <div className="flex flex-1 flex-col justify-end px-6 pb-8 pt-16 text-nav-text sm:flex-none sm:px-2 sm:pb-6 sm:pt-0">
        <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-lime text-2xl font-extrabold text-on-lime">N</span>
        <h1 className="text-4xl font-extrabold tracking-tight">Регистрация</h1>
        <p className="mt-1 text-[15px] font-semibold text-nav-muted">По коду приглашения от владельца</p>
      </div>
      <form
        onSubmit={onSubmit}
        className="w-full space-y-4 rounded-t-3xl bg-surface p-6 pb-[max(24px,var(--safe-bottom))] sm:max-w-sm sm:rounded-3xl sm:pb-6"
      >
        {error && <p className="rounded-2xl bg-danger-soft px-4 py-3 text-sm font-semibold text-danger">{error}</p>}
        <div className="space-y-1">
          <label className="text-xs font-extrabold uppercase tracking-wider text-subtle">Имя</label>
          <input
            name="name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="h-12 w-full rounded-2xl border-0 bg-muted px-4 text-[15px] outline-none focus:ring-2 focus:ring-brand/40"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-extrabold uppercase tracking-wider text-subtle">Логин</label>
          <input
            type="text"
            name="username"
            required
            minLength={3}
            pattern="[a-zA-Z0-9_.-]+"
            title="Латиница, цифры, точка, дефис, подчёркивание"
            autoComplete="username"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="h-12 w-full rounded-2xl border-0 bg-muted px-4 text-[15px] outline-none focus:ring-2 focus:ring-brand/40"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs font-extrabold uppercase tracking-wider text-subtle">Пароль</label>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              name="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-12 w-full rounded-2xl border-0 bg-muted px-4 pr-12 text-[15px] outline-none focus:ring-2 focus:ring-brand/40"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              title={showPassword ? "Скрыть пароль" : "Показать пароль"}
              className="absolute right-0 top-0 flex h-full w-10 items-center justify-center text-subtle hover:text-secondary"
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>
        <div className="space-y-1">
          <label className="text-xs font-extrabold uppercase tracking-wider text-subtle">Инвайт-код</label>
          <input
            type="text"
            name="invite_code"
            required
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            placeholder="Получи у того, кто уже пользуется"
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm uppercase"
          />
        </div>
        <button
          type="submit"
          disabled={register.isPending}
          className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-accent px-3 text-[15px] font-extrabold text-on-accent disabled:opacity-50"
        >
          {register.isPending && <Spinner />}
          {register.isPending ? "Создаём…" : "Создать аккаунт"}
        </button>
        <p className="text-center text-sm text-subtle">
          Уже есть аккаунт?{" "}
          <Link to="/login" className="text-primary underline">
            Войти
          </Link>
        </p>
      </form>
    </div>
  );
}

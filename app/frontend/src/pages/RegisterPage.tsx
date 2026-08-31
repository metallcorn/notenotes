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
    <div className="flex min-h-dvh items-center justify-center bg-muted p-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-lg border bg-surface p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-primary">Регистрация</h1>
        {error && <p className="rounded bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
        <div className="space-y-1">
          <label className="text-sm text-secondary">Имя</label>
          <input
            name="name"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded border px-3 py-2 text-sm"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm text-secondary">Логин</label>
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
            className="w-full rounded border px-3 py-2 text-sm"
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm text-secondary">Пароль</label>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              name="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded border px-3 py-2 pr-10 text-sm"
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
          <label className="text-sm text-secondary">Инвайт-код</label>
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
          className="flex w-full items-center justify-center gap-2 rounded bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
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

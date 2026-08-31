import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { useLogin } from "../api/hooks";
import { ApiError } from "../api/client";
import Spinner from "../components/Spinner";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const login = useLogin();
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    // Читаем значения из живого DOM формы, а не из React-state: на телефонах
    // автозаполнение пароль-менеджером иногда меняет value поля напрямую,
    // не вызывая onChange — тогда state молча остаётся пустым/старым, а
    // пользователь на глаз видит заполненные поля и не понимает, откуда
    // "неверный пароль".
    const data = new FormData(e.currentTarget);
    const usernameValue = String(data.get("username") ?? "").trim();
    const passwordValue = String(data.get("password") ?? "").trim();
    try {
      await login.mutateAsync({ username: usernameValue, password: passwordValue });
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось войти");
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-muted p-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-lg border bg-surface p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-primary">Notenotes</h1>
        {error && <p className="rounded bg-danger/10 px-3 py-2 text-sm text-danger">{error}</p>}
        <div className="space-y-1">
          <label className="text-sm text-secondary">Логин</label>
          <input
            type="text"
            name="username"
            required
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
              autoComplete="current-password"
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
        <button
          type="submit"
          disabled={login.isPending}
          className="flex w-full items-center justify-center gap-2 rounded bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {login.isPending && <Spinner />}
          {login.isPending ? "Входим…" : "Войти"}
        </button>
        <p className="text-center text-sm text-subtle">
          Нет аккаунта?{" "}
          <Link to="/register" className="text-primary underline">
            Зарегистрироваться
          </Link>
        </p>
      </form>
    </div>
  );
}

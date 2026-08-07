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
    <div className="flex min-h-dvh items-center justify-center bg-slate-50 p-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-lg border bg-white p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-900">Notenotes</h1>
        {error && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <div className="space-y-1">
          <label className="text-sm text-slate-600">Логин</label>
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
          <label className="text-sm text-slate-600">Пароль</label>
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
              className="absolute right-0 top-0 flex h-full w-10 items-center justify-center text-slate-400 hover:text-slate-700"
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>
        <button
          type="submit"
          disabled={login.isPending}
          className="flex w-full items-center justify-center gap-2 rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {login.isPending && <Spinner />}
          {login.isPending ? "Входим…" : "Войти"}
        </button>
        <p className="text-center text-sm text-slate-500">
          Нет аккаунта?{" "}
          <Link to="/register" className="text-slate-900 underline">
            Зарегистрироваться
          </Link>
        </p>
      </form>
    </div>
  );
}

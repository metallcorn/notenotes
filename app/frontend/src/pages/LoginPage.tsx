import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { useLogin } from "../api/hooks";
import { ApiError } from "../api/client";
import Spinner from "../components/Spinner";
import { safeNextPath } from "../lib/safeNext";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const login = useLogin();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

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
      // Вернуться туда, откуда прислали. Нужно для OAuth: не вошедшего
      // отправляют сюда с /api/oauth/authorize, и без возврата поток
      // подключения обрывался бы на пустом месте.
      const next = safeNextPath(searchParams.get("next"));
      // Наш собственный маршрутизатор не знает про /api/* — это бэкенд.
      // Туда уходим полной перезагрузкой, внутрь приложения — навигацией.
      if (next.startsWith("/api/")) window.location.href = next;
      else navigate(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Не удалось войти");
    }
  }

  return (
    // Макет «Вход» (21.10): тёмный верх с названием, форма — светлая
    // карточка снизу. На широком экране карточка центрируется.
    <div className="flex min-h-dvh flex-col bg-nav sm:items-center sm:justify-center sm:p-4">
      <div className="flex flex-1 flex-col justify-end px-6 pb-8 pt-16 text-nav-text sm:flex-none sm:px-2 sm:pb-6 sm:pt-0">
        <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-lime text-2xl font-extrabold text-on-lime">N</span>
        <h1 className="text-4xl font-extrabold tracking-tight">Notenotes</h1>
        <p className="mt-1 text-[15px] font-semibold text-nav-muted">Заметки, файлы и всё, что важно, — в одном месте</p>
      </div>
      <form
        onSubmit={onSubmit}
        className="w-full space-y-4 rounded-t-3xl bg-surface p-6 pb-[max(24px,var(--safe-bottom))] sm:max-w-sm sm:rounded-3xl sm:pb-6"
      >
        {error && <p className="rounded-2xl bg-danger-soft px-4 py-3 text-sm font-semibold text-danger">{error}</p>}
        <div className="space-y-1">
          <label className="text-xs font-extrabold uppercase tracking-wider text-subtle">Логин</label>
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
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-12 w-full rounded-2xl border-0 bg-muted px-4 pr-12 text-[15px] outline-none focus:ring-2 focus:ring-brand/40"
            />
            <button
              type="button"
              onClick={() => setShowPassword((v) => !v)}
              title={showPassword ? "Скрыть пароль" : "Показать пароль"}
              className="absolute right-0 top-0 flex h-full w-12 items-center justify-center text-subtle hover:text-secondary"
            >
              {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
          </div>
        </div>
        <button
          type="submit"
          disabled={login.isPending}
          className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-accent px-3 text-[15px] font-extrabold text-on-accent disabled:opacity-50"
        >
          {login.isPending && <Spinner />}
          {login.isPending ? "Входим…" : "Войти"}
        </button>
        <p className="text-center text-sm font-semibold text-subtle">
          Нет аккаунта?{" "}
          <Link to="/register" className="text-primary underline">
            Зарегистрироваться
          </Link>
        </p>
      </form>
    </div>
  );
}

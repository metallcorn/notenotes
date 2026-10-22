import { FormEvent, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Eye, EyeOff } from "lucide-react";
import { useLogin } from "../api/hooks";
import { ApiError } from "../api/client";
import Spinner from "../components/Spinner";
import { safeNextPath } from "../lib/safeNext";
import { t } from "../i18n";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [searchParamsInit] = useSearchParams();
  // Из Telegram Mini App сюда попадают, если бот не привязан к аккаунту
  // (App.tsx::RequireAuth): причина — в параметре tg.
  const [error, setError] = useState<string | null>(searchParamsInit.get("tg"));
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

  const chips = t("login.chips").split("|");

  return (
    // Макет «Вход» (21.10): тёмный верх с лаймовой плиткой «nn», крупным
    // слоганом и чипами возможностей, форма — светлая карточка снизу. На
    // широком экране карточка центрируется.
    <div className="flex min-h-dvh flex-col bg-nav sm:items-center sm:justify-center sm:p-4">
      <div className="flex flex-1 flex-col justify-end px-7 pb-8 pt-16 text-nav-text sm:flex-none sm:px-2 sm:pb-6 sm:pt-0">
        <span className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-lime text-[30px] font-extrabold tracking-tighter text-on-lime">
          nn
        </span>
        <h1 className="text-[44px] font-extrabold leading-none tracking-tighter">{t("login.tagline")}</h1>
        <p className="mt-3.5 text-base font-medium leading-snug text-nav-muted">{t("login.sub")}</p>
        <div className="mt-6 flex flex-wrap gap-2">
          {chips.map((c, i) => (
            <span
              key={c}
              className={`rounded-full px-3 py-2 text-[13px] font-bold ${i === 2 ? "bg-brand text-white" : "bg-white/10 text-nav-text"}`}
            >
              {c}
            </span>
          ))}
        </div>
      </div>
      <form
        onSubmit={onSubmit}
        className="w-full space-y-3 rounded-t-3xl bg-app p-5 pb-[max(34px,var(--safe-bottom))] sm:max-w-sm sm:rounded-3xl sm:pb-6"
      >
        {error && <p className="rounded-2xl bg-danger-soft px-4 py-3 text-sm font-semibold text-danger">{error}</p>}
        <label className="block space-y-1.5">
          <span className="text-[13px] font-bold text-secondary">{t("login.username")}</span>
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
            className="h-[52px] w-full rounded-2xl border-[1.5px] border-default bg-surface px-4 text-base text-primary outline-none focus:border-brand"
          />
        </label>
        <label className="block space-y-1.5">
          <span className="text-[13px] font-bold text-secondary">{t("login.password")}</span>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              name="password"
              required
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-[52px] w-full rounded-2xl border-[1.5px] border-default bg-surface px-4 pr-12 text-base text-primary outline-none focus:border-brand"
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
        </label>
        <button
          type="submit"
          disabled={login.isPending}
          className="mt-1 flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-accent px-3 text-base font-extrabold text-on-accent disabled:opacity-50"
        >
          {login.isPending && <Spinner />}
          {login.isPending ? "Входим…" : t("login.submit")}
        </button>
        <p className="pt-1 text-center text-[13px] font-semibold text-subtle">
          {t("login.invite")}{" "}
          <Link to="/register" className="font-extrabold text-primary">
            {t("login.register")}
          </Link>
        </p>
      </form>
    </div>
  );
}

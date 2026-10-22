import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useRef, useState } from "react";
import { useMe, useTelegramMiniAppLogin } from "./api/hooks";
import { getTelegramInitData, isTelegramMiniApp } from "./lib/telegramMiniApp";
import { useBoundedRestoring } from "./lib/useBoundedRestoring";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import InviteAcceptPage from "./pages/InviteAcceptPage";
import PublicNotePage from "./pages/PublicNotePage";
import AppShell from "./pages/AppShell";
import FeedbackWidget from "./components/FeedbackWidget";
import ErrorBoundary from "./components/ErrorBoundary";
import Spinner from "./components/Spinner";

// Тот же тёмный фон, что background_color в манифесте и заглушка в
// index.html — без этого промежуточный экран был белым с едва заметным
// серым текстом, реальные жалобы читали это как "белый экран и ничего"
// (казался сломанным, а не загружающимся).
function LoadingScreen() {
  return (
    <div
      className="flex min-h-dvh items-center justify-center gap-2 bg-slate-800 text-subtle"
      style={{
        boxSizing: "border-box",
        paddingTop: "var(--safe-top)",
        paddingRight: "var(--safe-right)",
        paddingBottom: "var(--safe-bottom)",
        paddingLeft: "var(--safe-left)",
      }}
    >
      <Spinner size={16} />
      Загрузка…
    </div>
  );
}

function RequireAuth({ children }: { children: ReactElement }) {
  // Только !user, не isError: react-query держит последние успешные данные
  // даже когда фоновый рефетч ("me" не stale, но на возврате фокуса всё
  // равно перепроверяется) падает — офлайн (ТЗ §18) это норма, не признак
  // разлогина. Раньше isError гонял в бесконечный редирект-пинг-понг
  // "/" → /login (там user из кэша есть, обратно на "/") → снова ошибка
  // сети → /login — сотни запросов /api/auth/me в секунду и пустой экран,
  // поймано на офлайн-тестах.
  const { data: user, isLoading } = useMe();
  // isRestoring (с верхней границей, см. useBoundedRestoring): пока
  // PersistQueryClientProvider гидрирует кэш из IndexedDB, query ещё
  // "pending", но не "fetching" (fetchStatus idle), поэтому react-query
  // отдаёт isLoading=false при ПУСТОМ data ещё до того, как персистнутый
  // (или сетевой) ответ реально подъехал. Без этой проверки !user на миг
  // становится true при каждом обновлении страницы — редирект на /login и
  // сразу обратно на "/" стирал query-параметры (?item=/?list=1) до того,
  // как их успевал восстановить AppShell (реальная жалоба — жест
  // «назад»/обновление сбрасывали место).
  const isRestoring = useBoundedRestoring();
  // Telegram Mini App: сессии нет — входим подписью initData, а не
  // отправляем на форму логина. Один раз: повторная попытка с той же
  // строкой бессмысленна, Telegram её не обновит без перезапуска.
  const tgLogin = useTelegramMiniAppLogin();
  const tgTried = useRef(false);
  const [tgError, setTgError] = useState<string | null>(null);
  const needTgLogin = isTelegramMiniApp() && !isLoading && !isRestoring && !user && !tgTried.current;
  useEffect(() => {
    if (!needTgLogin) return;
    tgTried.current = true;
    tgLogin.mutate(getTelegramInitData(), {
      onError: (err) => setTgError(err instanceof Error ? err.message : "Не удалось войти через Telegram"),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needTgLogin]);

  if (isLoading || isRestoring || needTgLogin || tgLogin.isPending) {
    return <LoadingScreen />;
  }
  if (!user) {
    return <Navigate to={tgError ? `/login?tg=${encodeURIComponent(tgError)}` : "/login"} replace />;
  }
  return children;
}

// Обратный случай: уже залогиненный пользователь попадает на /login или
// /register, например браузерной кнопкой «назад» (эти страницы остаются
// в истории после логина) — незачем снова показывать форму входа.
function RedirectIfAuthed({ children }: { children: ReactElement }) {
  const { data: user, isLoading } = useMe();
  const isRestoring = useBoundedRestoring();

  if (isLoading || isRestoring) {
    return <LoadingScreen />;
  }
  if (user) {
    return <Navigate to="/" replace />;
  }
  return children;
}

export default function App() {
  return (
    <>
      <Routes>
        <Route
          path="/login"
          element={
            <RedirectIfAuthed>
              <LoginPage />
            </RedirectIfAuthed>
          }
        />
        <Route
          path="/register"
          element={
            <RedirectIfAuthed>
              <RegisterPage />
            </RedirectIfAuthed>
          }
        />
        <Route
          path="/invites/:token"
          element={
            <RequireAuth>
              <InviteAcceptPage />
            </RequireAuth>
          }
        />
        {/* Без RequireAuth/RedirectIfAuthed сознательно — публичная
            страница не должна зависеть от состояния авторизации вообще,
            анонимный посетитель не имеет и не должен иметь сессию. */}
        <Route path="/s/:token" element={<PublicNotePage />} />
        <Route
          path="/*"
          element={
            <RequireAuth>
              <ErrorBoundary>
                <AppShell />
              </ErrorBoundary>
            </RequireAuth>
          }
        />
      </Routes>
      <FeedbackWidget />
    </>
  );
}

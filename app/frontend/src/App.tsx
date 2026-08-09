import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useMe } from "./api/hooks";
import { useBoundedRestoring } from "./lib/useBoundedRestoring";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
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
    <div className="flex min-h-dvh items-center justify-center gap-2 bg-slate-800 text-slate-400">
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

  if (isLoading || isRestoring) {
    return <LoadingScreen />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
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

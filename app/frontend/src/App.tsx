import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useMe } from "./api/hooks";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import AppShell from "./pages/AppShell";
import FeedbackWidget from "./components/FeedbackWidget";
import ErrorBoundary from "./components/ErrorBoundary";

function RequireAuth({ children }: { children: ReactElement }) {
  // Только !user, не isError: react-query держит последние успешные данные
  // даже когда фоновый рефетч ("me" не stale, но на возврате фокуса всё
  // равно перепроверяется) падает — офлайн (ТЗ §18) это норма, не признак
  // разлогина. Раньше isError гонял в бесконечный редирект-пинг-понг
  // "/" → /login (там user из кэша есть, обратно на "/") → снова ошибка
  // сети → /login — сотни запросов /api/auth/me в секунду и пустой экран,
  // поймано на офлайн-тестах.
  const { data: user, isLoading } = useMe();

  if (isLoading) {
    return <div className="flex min-h-dvh items-center justify-center text-slate-400">Загрузка…</div>;
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

  if (isLoading) {
    return <div className="flex min-h-dvh items-center justify-center text-slate-400">Загрузка…</div>;
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

import type { ReactElement } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useMe } from "./api/hooks";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import AppShell from "./pages/AppShell";
import FeedbackWidget from "./components/FeedbackWidget";

function RequireAuth({ children }: { children: ReactElement }) {
  const { data: user, isLoading, isError } = useMe();

  if (isLoading) {
    return <div className="flex min-h-dvh items-center justify-center text-slate-400">Загрузка…</div>;
  }
  if (isError || !user) {
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
              <AppShell />
            </RequireAuth>
          }
        />
      </Routes>
      <FeedbackWidget />
    </>
  );
}

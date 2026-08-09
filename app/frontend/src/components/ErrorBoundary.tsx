import { Component, type ErrorInfo, type ReactNode } from "react";
import { diagnosticLog } from "../lib/diagnostics";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

// Без этого любая необработанная ошибка рендера (например, из TipTap/tippy.js,
// которые управляют частью DOM в обход React) сносит всё дерево — пользователь
// видит просто белый экран без единого намёка на то, что произошло. Кнопка
// «Отзыв» вынесена в App.tsx вне этой границы, так что репортить баг всё ещё
// можно даже после срабатывания.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Необработанная ошибка рендера:", error, info.componentStack);
    diagnosticLog("error_boundary_caught", {
      message: error.message,
      stack: error.stack?.slice(0, 2000),
      componentStack: info.componentStack?.slice(0, 2000),
    });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center">
          <p className="text-lg font-medium text-slate-700">Что-то пошло не так</p>
          <p className="max-w-sm text-sm text-slate-500">
            Экран сломался из-за неожиданной ошибки. Попробуйте обновить страницу — если повторится,
            оставьте отзыв кнопкой внизу справа, мы посмотрим.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="rounded bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800"
          >
            Обновить страницу
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

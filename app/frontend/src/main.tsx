import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient } from "@tanstack/react-query";
import { PersistQueryClientProvider } from "@tanstack/react-query-persist-client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { idbPersister } from "./lib/queryPersister";
import { diagnosticLog } from "./lib/diagnostics";
import "./index.css";

// Точечная диагностика бага "белый экран в standalone PWA" (см.
// diagnostics.ts) — если причина в необработанном исключении где-то в
// рендере/эффекте (ErrorBoundary ловит не всё, например ошибки вне React,
// в промисах), это единственный шанс узнать о нём с реального устройства.
window.addEventListener("error", (e) => {
  diagnosticLog("window_error", { message: e.message, filename: e.filename, lineno: e.lineno, stack: e.error?.stack?.slice(0, 2000) });
});
window.addEventListener("unhandledrejection", (e) => {
  diagnosticLog("unhandled_rejection", { reason: String(e.reason).slice(0, 2000) });
});

const queryClient = new QueryClient({
  // refetchOnWindowFocus включён нарочно (это стандартное поведение
  // react-query, но было явно выключено) — жалоба пользователя: ведёт
  // диалог на телефоне, переключается на комп, хочет видеть уже
  // отправленные сообщения без ручного обновления страницы. Возврат
  // фокуса на вкладку — тот момент, когда стоит перепроверить с сервером.
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: true } },
});

// Гасим фолбэк "не удалось загрузить" из index.html — до этой строки
// дошли, значит модульный граф загрузился и React готов рендерить
// (см. комментарий в index.html про таймаут).
clearTimeout((window as unknown as { __notenotesBootTimeout: number }).__notenotesBootTimeout);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <PersistQueryClientProvider
      client={queryClient}
      persistOptions={{
        persister: idbPersister,
        // Специально большой: цель — данные доступны офлайн сколько угодно
        // долго, а не выбрасываются по возрасту именно тогда, когда их
        // неоткуда обновить. Актуальность — через refetchOnWindowFocus
        // выше, когда сеть вернётся, а не через выбрасывание по maxAge.
        maxAge: 1000 * 60 * 60 * 24 * 30,
      }}
    >
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </PersistQueryClientProvider>
  </React.StrictMode>,
);

// PWA-установка (кнопка "На главный экран"/"Установить"). Только в проде —
// в dev-сборке (если она когда-нибудь понадобится) сервис-воркер только
// мешал бы горячей перезагрузке.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js");
  });
}

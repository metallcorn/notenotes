import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  // refetchOnWindowFocus включён нарочно (это стандартное поведение
  // react-query, но было явно выключено) — жалоба пользователя: ведёт
  // диалог на телефоне, переключается на комп, хочет видеть уже
  // отправленные сообщения без ручного обновления страницы. Возврат
  // фокуса на вкладку — тот момент, когда стоит перепроверить с сервером.
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: true } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);

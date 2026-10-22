// Telegram Mini App: приложение открывается внутри Telegram (кнопка меню
// бота или кнопка «Открыть» под сообщением). Telegram кладёт initData в
// хеш адреса (#tgWebAppData=…) и даёт SDK telegram-web-app.js. Вход —
// подписью initData (POST /api/auth/telegram-miniapp), без пароля.

type TelegramWebApp = {
  initData: string;
  ready: () => void;
  expand: () => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  colorScheme?: "light" | "dark";
  contentSafeAreaInset?: { top: number; bottom: number; left: number; right: number };
  safeAreaInset?: { top: number; bottom: number; left: number; right: number };
  onEvent?: (event: string, handler: () => void) => void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}

const SDK_URL = "https://telegram.org/js/telegram-web-app.js";
let cachedInitData: string | null = null;

function initDataFromHash(): string | null {
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash.includes("tgWebAppData")) return null;
  const params = new URLSearchParams(hash);
  return params.get("tgWebAppData");
}

// Запоминаем сразу при загрузке: роутер позже перепишет адрес, и хеш с
// initData пропадёт.
export function isTelegramMiniApp(): boolean {
  if (cachedInitData === null) cachedInitData = initDataFromHash() ?? window.Telegram?.WebApp?.initData ?? "";
  return cachedInitData !== "";
}

export function getTelegramInitData(): string {
  return isTelegramMiniApp() ? cachedInitData! : "";
}

function applySafeArea(app: TelegramWebApp) {
  const content = app.contentSafeAreaInset;
  const device = app.safeAreaInset;
  if (!content && !device) return;
  const root = document.documentElement.style;
  root.setProperty("--safe-top", `${(content?.top ?? 0) + (device?.top ?? 0)}px`);
  root.setProperty("--safe-bottom", `${(content?.bottom ?? 0) + (device?.bottom ?? 0)}px`);
  root.setProperty("--safe-left", `${(content?.left ?? 0) + (device?.left ?? 0)}px`);
  root.setProperty("--safe-right", `${(content?.right ?? 0) + (device?.right ?? 0)}px`);
}

// Подключает SDK (только внутри Telegram — в обычном браузере лишний
// внешний скрипт не нужен), разворачивает на весь экран и подгоняет
// цвета шапки под тему приложения.
export function initTelegramMiniApp(): void {
  if (!isTelegramMiniApp()) return;
  const setup = () => {
    const app = window.Telegram?.WebApp;
    if (!app) return;
    try {
      app.ready();
      app.expand();
      const dark = document.documentElement.classList.contains("dark");
      app.setHeaderColor?.(dark ? "#0e0e12" : "#f5f4ef");
      app.setBackgroundColor?.(dark ? "#0e0e12" : "#f5f4ef");
      applySafeArea(app);
      app.onEvent?.("safeAreaChanged", () => applySafeArea(app));
      app.onEvent?.("contentSafeAreaChanged", () => applySafeArea(app));
    } catch {
      // SDK старой версии без части методов — приложение работает и так.
    }
  };
  if (window.Telegram?.WebApp) {
    setup();
    return;
  }
  const script = document.createElement("script");
  script.src = SDK_URL;
  script.async = true;
  script.onload = setup;
  document.head.appendChild(script);
}

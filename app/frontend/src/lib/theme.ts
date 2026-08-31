import { uiStorage, type Theme } from "./storage";

// Держим синхронно с --color-bg-app в index.css — CSS сам себя не может
// вписать в <meta name="theme-color"> (адресная строка браузера/PWA-шапка).
const THEME_COLOR_META: Record<"light" | "dark", string> = {
  light: "#ffffff",
  dark: "#202326",
};

export function resolveTheme(theme: Theme): "light" | "dark" {
  if (theme === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return theme;
}

export function applyTheme(theme: Theme): void {
  const resolved = resolveTheme(theme);
  document.documentElement.classList.toggle("dark", resolved === "dark");
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR_META[resolved]);
}

export function setTheme(theme: Theme): void {
  uiStorage.setTheme(theme);
  applyTheme(theme);
}

// Реальная просьба: режим "Системная" должен живо реагировать на смену
// темы ОС, пока приложение открыто, а не только при следующей перезагрузке
// страницы. onChange вызывается только если ПОЛЬЗОВАТЕЛЬ сейчас в режиме
// "system" — вызывающий код сам решает, актуально ли ещё подписываться.
export function watchSystemTheme(onChange: () => void): () => void {
  const mq = window.matchMedia("(prefers-color-scheme: dark)");
  mq.addEventListener("change", onChange);
  return () => mq.removeEventListener("change", onChange);
}

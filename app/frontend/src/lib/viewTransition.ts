// Плавный переход между состояниями UI (переключение мобильной панели,
// схлопывание сайдбара/списка) через View Transitions API — но не в
// standalone-режиме PWA. Три отдельных инцидента подряд (перехват
// diagnostics.ts, реальное устройство — Android Firefox, standalone),
// каждый с новой гонкой в самом API: "AbortError: Skipped ViewTransition
// due to another transition starting" (наложение двух переходов), затем
// "InvalidStateError: Skipped ViewTransition due to document being
// hidden" (жест «назад» на время держит страницу hidden), и наконец
// зависание интерфейса на самом обычном холодном старте — restoration-
// эффект в AppShell всегда делает replace-на-базу и следом push-на-
// список ДВУМЯ отдельными вызовами withViewTransition подряд, то есть
// это не редкий краевой случай жеста, а КАЖДЫЙ запуск PWA. Каждый раз
// патчили конкретную гонку, но источник один и тот же API — точка,
// где продолжать чинить накладнее, чем просто не использовать его в
// этом режиме: это прогрессивное улучшение (сам код это подчёркивал с
// самого начала), а не обязательная часть логики, и standalone-режим на
// этом устройстве явно не тянет его надёжно. В обычной вкладке браузера
// поводов для жалоб не было — там API остаётся.
export function withViewTransition(fn: () => void): void {
  const doc = document as Document & { startViewTransition?: (callback: () => void) => void };
  const isStandalone = typeof matchMedia === "function" && matchMedia("(display-mode: standalone)").matches;
  if (isStandalone || typeof doc.startViewTransition !== "function") {
    fn();
    return;
  }
  doc.startViewTransition(fn);
}

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
//
// opts.mobileOnly — реальный найденный баг: AppShell.tsx использует эту
// функцию и для переключения мобильного стека (sidebar/list/editor —
// на lg: и шире все три видны одновременно, mobileView визуально ничего
// не переключает), и для схлопывания панелей на десктопе (сайдбар/
// список — там переход РЕАЛЬНО нужен на любой ширине). Раньше первый
// случай всё равно гонял через startViewTransition на десктопе — с
// обычным коротким fade это было незаметно, но как только переход стал
// направленным слайдом (реальная жалоба на слайд-анимацию), на десктопе
// это стало выглядеть как "весь интерфейс перерисовывается и едет
// вбок" без всякой причины: снимать/анимировать там нечего. mobileOnly
// пропускает startViewTransition выше lg: (1024px, тот же брейкпоинт,
// что и весь остальной mobile/desktop-переключатель в приложении) —
// стейт обновляется мгновенно, без снимка.
type ViewTransitionLike = { ready?: Promise<void>; finished?: Promise<void> };

export function withViewTransition(fn: () => void, opts?: { mobileOnly?: boolean }): void {
  const doc = document as Document & {
    startViewTransition?: (callback: () => void) => ViewTransitionLike | undefined;
  };
  const isStandalone = typeof matchMedia === "function" && matchMedia("(display-mode: standalone)").matches;
  const isDesktop = opts?.mobileOnly && typeof matchMedia === "function" && matchMedia("(min-width: 1024px)").matches;
  if (isStandalone || isDesktop || typeof doc.startViewTransition !== "function") {
    fn();
    return;
  }
  const transition = doc.startViewTransition(fn);
  // Пропущенный переход — не ошибка, и молчать о нём надо явно.
  //
  // startViewTransition возвращает объект с промисами ready/finished, и
  // при пропуске перехода они ОТКЛОНЯЮТСЯ. Обработчика не было, поэтому
  // каждый такой случай улетал в unhandled rejection: 24 записи в
  // журнале фронтенда, последняя 07.10 — «Skipped ViewTransition due to
  // another transition starting» и «due to document being hidden».
  //
  // Для нас это штатные ситуации: два перехода подряд (restoration в
  // AppShell) и уход страницы в фон. DOM к этому моменту уже обновлён
  // колбэком — пропущена только анимация, то есть ровно то
  // «прогрессивное улучшение», о котором говорит комментарий выше.
  // Поэтому гасим, а не чиним: чинить тут нечего.
  transition?.ready?.catch(() => {});
  transition?.finished?.catch(() => {});
}

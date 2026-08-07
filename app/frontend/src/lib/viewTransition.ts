// Плавный переход между состояниями UI (переключение мобильной панели,
// схлопывание сайдбара/списка) через View Transitions API. Не во всех
// браузерах есть — тогда просто применяем изменение без анимации, а не
// падаем: это прогрессивное улучшение, а не обязательная часть логики.
export function withViewTransition(fn: () => void): void {
  const doc = document as Document & { startViewTransition?: (callback: () => void) => void };
  if (typeof doc.startViewTransition === "function") {
    doc.startViewTransition(fn);
  } else {
    fn();
  }
}

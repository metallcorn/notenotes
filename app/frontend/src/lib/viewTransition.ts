// Плавный переход между состояниями UI (переключение мобильной панели,
// схлопывание сайдбара/списка) через View Transitions API. Не во всех
// браузерах есть — тогда просто применяем изменение без анимации, а не
// падаем: это прогрессивное улучшение, а не обязательная часть логики.
type ViewTransition = { finished: Promise<void>; skipTransition: () => void };
type DocumentWithViewTransition = Document & { startViewTransition?: (callback: () => void) => ViewTransition };

// Если запустить startViewTransition, пока предыдущий переход ещё не
// закончился, браузер обрывает СТАРЫЙ ("AbortError: Skipped ViewTransition
// due to another transition starting") — само состояние (наш callback)
// применяется всё равно, но сам API-переход может оставить DOM в
// промежуточном визуальном состоянии (снэпшот старого экрана поверх
// настоящего). Поймано диагностикой на реальном устройстве (Android
// Firefox, standalone PWA) — двойной popstate от жеста «назад» укладывал
// два вызова в ~180мс, ровно в длительность самой анимации (index.css) —
// именно тот белый экран из отзыва. Раз уже идёт переход — не начинаем
// новый API-переход поверх него, просто применяем следующее состояние
// без анимации; это гарантированно не ломает рендер, максимум — пропуск
// одной анимации подряд.
let currentTransition: ViewTransition | null = null;

export function withViewTransition(fn: () => void): void {
  const doc = document as DocumentWithViewTransition;
  if (typeof doc.startViewTransition !== "function") {
    fn();
    return;
  }
  if (currentTransition) {
    fn();
    return;
  }
  // document.hidden — вторая гонка, пойманная той же диагностикой уже
  // после фикса выше: системный жест «назад» на Android какое-то время
  // держит страницу скрытой (предпросмотр анимации), и в этот момент
  // startViewTransition падает с "InvalidStateError: Skipped
  // ViewTransition due to document being hidden" — по спеку не
  // гарантировано, что callback вообще будет вызван в этом случае, то
  // есть само состояние (какая панель показана) могло вообще не
  // применяться. Тут та же защита: не идти через API-переход, если
  // документ скрыт, применить состояние напрямую.
  if (doc.hidden) {
    fn();
    return;
  }
  const transition = doc.startViewTransition(fn);
  currentTransition = transition;
  transition.finished.catch(() => {}).finally(() => {
    if (currentTransition === transition) currentTransition = null;
  });
}

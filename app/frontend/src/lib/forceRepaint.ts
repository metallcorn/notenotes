// Диагностика (viewTransition.ts, три инцидента подряд) исключила JS —
// логи показывают, что React-состояние на каждом переходе обновляется
// верно, ошибок нет вообще, но экран остаётся белым, пока по нему не
// тапнешь — то есть DOM правильный, а перерисовки не происходит. Это
// известный класс багов: системный жест «назад» на Android (особенно
// predictive back с превью-анимацией) оставляет компоузер GeckoView в
// «устаревшем» состоянии именно в standalone PWA — сам сайт тут ничего
// не может сделать правильно/неправильно, только принудительно попросить
// браузер перерисоваться. visibilitychange — момент, когда страница
// возвращается в фокус после такого жеста; трюк — тронуть layout
// (чтение offsetHeight форсирует синхронный reflow) сразу после смены
// transform, это самый дешёвый кросс-браузерный способ форсировать
// реальную перерисовку без видимого мигания.
//
// Проба diagnosticLog отсюда убрана 10.10: она лишь подтверждала, что
// обработчик сработал, и за два месяца записала 7 481 строку в журнал —
// то есть запрос к серверу на каждое возвращение вкладки в фокус.
export function installForceRepaintOnVisible(): void {
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    const root = document.getElementById("root");
    if (!root) return;
    root.style.transform = "translateZ(0)";
    // eslint-disable-next-line @typescript-eslint/no-unused-expressions
    root.offsetHeight;
    root.style.transform = "";
  });
}

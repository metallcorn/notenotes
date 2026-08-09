// Точечная диагностика одного бага — белый экран в standalone PWA на
// Android Firefox при переходе список заметок → sidebar, который не
// воспроизводится ни в Chromium, ни в Firefox через Playwright (см.
// историю коммитов). Шлём состояние экрана в момент перехода на сервер
// через sendBeacon — он не блокирует навигацию и переживает выгрузку
// страницы, в отличие от обычного fetch. Временный инструмент под одно
// расследование, не общий механизм логирования.
export function diagnosticLog(event: string, data: Record<string, unknown> = {}): void {
  try {
    const payload = JSON.stringify({
      event,
      data: {
        ...data,
        ts: Date.now(),
        url: location.pathname + location.search,
        historyLength: history.length,
        displayModeStandalone: matchMedia("(display-mode: standalone)").matches,
        innerWidth: window.innerWidth,
        innerHeight: window.innerHeight,
        visualViewportHeight: window.visualViewport?.height ?? null,
        visualViewportOffsetTop: window.visualViewport?.offsetTop ?? null,
        docClientHeight: document.documentElement.clientHeight,
        userAgent: navigator.userAgent,
      },
    });
    const blob = new Blob([payload], { type: "application/json" });
    if (!navigator.sendBeacon?.("/api/debug-log", blob)) {
      fetch("/api/debug-log", { method: "POST", headers: { "Content-Type": "application/json" }, body: payload, keepalive: true }).catch(
        () => {},
      );
    }
  } catch {
    // Диагностика не должна ронять реальную навигацию, даже если сама сломалась.
  }
}

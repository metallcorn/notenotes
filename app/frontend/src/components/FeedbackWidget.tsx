import { useEffect, useRef, useState } from "react";

type Status = "idle" | "sending" | "sent" | "error";

// Плавающая кнопка в углу экрана рано или поздно перекрывает чей-то
// элемент управления: то "Отправить" в чате ассистента, то кнопку профиля
// в сайдбаре — на любом экране какой-то нижний угол всегда занят чем-то
// своим. Поэтому это обычное модальное окно по центру (как ConfirmDialog/
// SettingsModal), без плавающего триггера — открывается только из меню
// профиля (см. UserMenu.tsx), которое шлёт это событие.
export const OPEN_FEEDBACK_EVENT = "notenotes:open-feedback";

export default function FeedbackWidget() {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const widgetRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleOpen() {
      setOpen(true);
    }
    window.addEventListener(OPEN_FEEDBACK_EVENT, handleOpen);
    return () => window.removeEventListener(OPEN_FEEDBACK_EVENT, handleOpen);
  }, []);

  async function submit() {
    if (!message.trim()) return;
    setStatus("sending");

    // Прячем сам виджет перед скриншотом, чтобы он не попал в кадр —
    // иначе на каждом скриншоте было бы открытое окно отзыва поверх страницы.
    const widget = widgetRef.current;
    if (widget) widget.style.visibility = "hidden";
    await new Promise((resolve) => requestAnimationFrame(resolve));

    let blob: Blob | null = null;
    try {
      const html2canvas = (await import("html2canvas")).default;
      const canvas = await html2canvas(document.documentElement, { useCORS: true, logging: false });
      blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
    } catch {
      blob = null;
    } finally {
      if (widget) widget.style.visibility = "visible";
    }

    const form = new FormData();
    form.append("message", message);
    form.append("page_url", window.location.pathname + window.location.search);
    if (blob) form.append("screenshot", blob, "screenshot.png");

    try {
      const res = await fetch("/api/feedback", { method: "POST", body: form, credentials: "include" });
      if (!res.ok) throw new Error("request failed");
      setStatus("sent");
      setMessage("");
      setTimeout(() => {
        setOpen(false);
        setStatus("idle");
      }, 1500);
    } catch {
      setStatus("error");
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setOpen(false)}>
      <div
        ref={widgetRef}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-lg border bg-white p-3 shadow-xl"
      >
        <div className="mb-2 text-sm font-medium text-slate-900">Отзыв</div>
        <textarea
          autoFocus
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Что не так или что улучшить? Скриншот текущей страницы приложится автоматически."
          rows={4}
          className="w-full resize-none rounded border px-2 py-1.5 text-sm outline-none"
        />
        {status === "error" && <p className="mt-1 text-xs text-red-600">Не отправилось, попробуйте ещё раз</p>}
        {status === "sent" && <p className="mt-1 text-xs text-green-600">Отправлено, спасибо!</p>}
        <div className="mt-2 flex justify-end gap-2">
          <button onClick={() => setOpen(false)} className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100">
            Отмена
          </button>
          <button
            onClick={submit}
            disabled={status === "sending" || !message.trim()}
            className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          >
            {status === "sending" ? "Отправка…" : "Отправить"}
          </button>
        </div>
      </div>
    </div>
  );
}

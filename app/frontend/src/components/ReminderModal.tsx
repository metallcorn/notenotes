import { useState } from "react";
import { AlarmClock } from "lucide-react";

// Реальный запрос: "через /notify создавать команду на создание
// напоминания — открывается форма, выбираешь дату/время, можешь написать
// текст". Тот же принцип подтверждения, что уже есть у кнопки "Напомнить"
// на карточке билета (TicketAttachmentCard.tsx) — явная форма с "Создать",
// не молчаливое действие по одному клику. datetime-local — нативный
// браузерный пикер: на телефоне открывает системный календарь/часы сам,
// без сторонней библиотеки.
export default function ReminderModal({
  defaultTitle,
  onCreate,
  onCancel,
}: {
  defaultTitle: string;
  onCreate: (data: { title: string; body: string; triggerAt: Date }) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(defaultTitle);
  const [body, setBody] = useState("");
  const [when, setWhen] = useState("");

  const valid = title.trim() && when;

  function submit() {
    if (!valid) return;
    // datetime-local отдаёт строку без таймзоны ("2026-08-19T09:00") —
    // new Date() парсит её как ЛОКАЛЬНОЕ время браузера, что и нужно:
    // пользователь выбирает время у себя на часах, а не в UTC.
    const triggerAt = new Date(when);
    if (Number.isNaN(triggerAt.getTime())) return;
    onCreate({ title: title.trim(), body: body.trim(), triggerAt });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-lg bg-white p-4 shadow-xl">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-900">
          <AlarmClock size={16} className="text-slate-500" />
          Новое напоминание
        </div>

        <label className="mb-2 block">
          <span className="mb-1 block text-xs text-slate-500">Заголовок</span>
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="О чём напомнить"
            className="w-full rounded border px-2 py-1.5 text-sm outline-none focus:border-slate-400"
          />
        </label>

        <label className="mb-2 block">
          <span className="mb-1 block text-xs text-slate-500">Подробности (необязательно)</span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={2}
            className="w-full resize-none rounded border px-2 py-1.5 text-sm outline-none focus:border-slate-400"
          />
        </label>

        <label className="mb-4 block">
          <span className="mb-1 block text-xs text-slate-500">Когда</span>
          <input
            type="datetime-local"
            lang="ru-RU"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            className="w-full rounded border px-2 py-1.5 text-sm outline-none focus:border-slate-400"
          />
        </label>

        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded px-3 py-1.5 text-sm text-slate-500 hover:bg-slate-100">
            Отмена
          </button>
          <button
            onClick={submit}
            disabled={!valid}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-40"
          >
            Создать
          </button>
        </div>
      </div>
    </div>
  );
}

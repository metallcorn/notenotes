import { useState } from "react";
import { AlarmClock } from "lucide-react";

import { REPEAT_LABELS, REPEAT_RULES, type RepeatRule } from "../lib/recurrence";

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
  onCreate: (data: { title: string; body: string; triggerAt: Date; repeat: RepeatRule | "" }) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState(defaultTitle);
  const [body, setBody] = useState("");
  const [when, setWhen] = useState("");
  // По умолчанию — без повтора. Повторяющееся напоминание, заведённое
  // случайно, раздражает каждый день и его надо идти отключать.
  const [repeat, setRepeat] = useState<RepeatRule | "">("");

  const valid = title.trim() && when;

  function submit() {
    if (!valid) return;
    // datetime-local отдаёт строку без таймзоны ("2026-08-19T09:00") —
    // new Date() парсит её как ЛОКАЛЬНОЕ время браузера, что и нужно:
    // пользователь выбирает время у себя на часах, а не в UTC.
    const triggerAt = new Date(when);
    if (Number.isNaN(triggerAt.getTime())) return;
    onCreate({ title: title.trim(), body: body.trim(), triggerAt, repeat });
  }

  return (
    <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-lg bg-surface p-4 shadow-xl">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-primary">
          <AlarmClock size={16} className="text-subtle" />
          Новое напоминание
        </div>

        <label className="mb-2 block">
          <span className="mb-1 block text-xs text-subtle">Заголовок</span>
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="О чём напомнить"
            className="w-full rounded border px-2 py-1.5 text-sm outline-none focus:border-strong"
          />
        </label>

        <label className="mb-2 block">
          <span className="mb-1 block text-xs text-subtle">Подробности (необязательно)</span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={2}
            className="w-full resize-none rounded border px-2 py-1.5 text-sm outline-none focus:border-strong"
          />
        </label>

        <label className="mb-2 block">
          <span className="mb-1 block text-xs text-subtle">Когда</span>
          <input
            type="datetime-local"
            lang="ru-RU"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            className="w-full rounded border px-2 py-1.5 text-sm outline-none focus:border-strong"
          />
        </label>

        <label className="mb-4 block">
          <span className="mb-1 block text-xs text-subtle">Повторять</span>
          <select
            value={repeat}
            onChange={(e) => setRepeat(e.target.value as RepeatRule | "")}
            className="w-full rounded border bg-surface px-2 py-1.5 text-sm outline-none focus:border-strong"
          >
            <option value="">не повторять</option>
            {REPEAT_RULES.map((rule) => (
              <option key={rule} value={rule}>
                {REPEAT_LABELS[rule]}
              </option>
            ))}
          </select>
          {repeat && (
            // Про это стоит сказать заранее: следующий раз заводится в
            // момент отправки, поэтому "удалить" на пришедшем напоминании
            // серию не остановит, а на ожидающем — остановит.
            <span className="mt-1 block text-[11px] text-subtle">
              Напоминание будет приходить {REPEAT_LABELS[repeat]}, пока его не удалить.
            </span>
          )}
        </label>

        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded px-3 py-1.5 text-sm text-subtle hover:bg-muted-hover">
            Отмена
          </button>
          <button
            onClick={submit}
            disabled={!valid}
            className="rounded bg-accent px-3 py-1.5 text-sm text-white disabled:opacity-40"
          >
            Создать
          </button>
        </div>
      </div>
    </div>
  );
}

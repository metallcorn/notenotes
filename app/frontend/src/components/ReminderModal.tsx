import { useState } from "react";
import { AlarmClock } from "lucide-react";

import { REPEAT_LABELS, REPEAT_RULES, type RepeatRule } from "../lib/recurrence";
import { dateLocale } from "../i18n";

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

  // Быстрые варианты (макет «Напоминание», 21.10) — заполняют то же поле
  // datetime-local, дальше всё как при ручном выборе. Строка формируется
  // в локальном времени, как и ожидает поле.
  function toLocalInput(d: Date): string {
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
  const quick: { label: string; at: () => Date }[] = [
    { label: "Через час", at: () => new Date(Date.now() + 3600_000) },
    {
      label: "Завтра 9:00",
      at: () => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        d.setHours(9, 0, 0, 0);
        return d;
      },
    },
    {
      label: "Через 3 дня",
      at: () => {
        const d = new Date();
        d.setDate(d.getDate() + 3);
        d.setHours(9, 0, 0, 0);
        return d;
      },
    },
    {
      label: "Через неделю",
      at: () => {
        const d = new Date();
        d.setDate(d.getDate() + 7);
        d.setHours(9, 0, 0, 0);
        return d;
      },
    },
  ];

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
      <div onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-3xl bg-surface p-4 shadow-xl">
        <h2 className="mb-3 flex items-center gap-2 text-2xl font-extrabold tracking-tight text-primary">
          <AlarmClock size={20} />
          Напомнить
        </h2>
        <div className="mb-3 flex flex-wrap gap-2">
          {quick.map((q) => {
            const value = toLocalInput(q.at());
            const active = when === value;
            return (
              <button
                key={q.label}
                type="button"
                onClick={() => setWhen(value)}
                className={`h-9 rounded-full px-3.5 text-[13px] font-bold transition-colors ${
                  active ? "bg-accent text-on-accent" : "bg-muted text-primary hover:bg-muted-hover"
                }`}
              >
                {q.label}
              </button>
            );
          })}
        </div>

        <label className="mb-2 block">
          <span className="mb-1 block text-[11px] font-extrabold uppercase tracking-wider text-subtle">Заголовок</span>
          <input
            autoFocus
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="О чём напомнить"
            className="h-11 w-full rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
          />
        </label>

        <label className="mb-2 block">
          <span className="mb-1 block text-[11px] font-extrabold uppercase tracking-wider text-subtle">Подробности (необязательно)</span>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={2}
            className="w-full resize-none rounded-xl border bg-surface px-3.5 py-2.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
          />
        </label>

        <label className="mb-2 block">
          <span className="mb-1 block text-[11px] font-extrabold uppercase tracking-wider text-subtle">Когда</span>
          <input
            type="datetime-local"
            lang={dateLocale}
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            className="h-11 w-full rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
          />
        </label>

        <label className="mb-4 block">
          <span className="mb-1 block text-[11px] font-extrabold uppercase tracking-wider text-subtle">Повторять</span>
          <select
            value={repeat}
            onChange={(e) => setRepeat(e.target.value as RepeatRule | "")}
            className="h-11 w-full rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
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
          <button onClick={onCancel} className="h-11 rounded-2xl px-4 text-sm font-bold text-secondary hover:bg-muted">
            Отмена
          </button>
          <button
            onClick={submit}
            disabled={!valid}
            className="h-11 rounded-2xl bg-accent px-5 text-sm font-extrabold text-on-accent disabled:opacity-40"
          >
            Создать
          </button>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { Bell, Repeat } from "lucide-react";

import { REPEAT_LABELS, REPEAT_RULES, type RepeatRule } from "../lib/recurrence";
import { dateLocale, t } from "../i18n";

// Реальный запрос: "через /notify создавать команду на создание
// напоминания — открывается форма, выбираешь дату/время, можешь написать
// текст". Тот же принцип подтверждения, что уже есть у кнопки "Напомнить"
// на карточке билета (TicketAttachmentCard.tsx) — явная форма с кнопкой,
// не молчаливое действие по одному клику.
//
// Макет «Напоминание» (21.10): быстрые варианты 2×2, под ними «или точно»
// — полоска ближайших семи дней и время, повтор, большая кнопка внизу с
// тем, что получится («Напомнить в пятницу в 12:00»).

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
function toDateInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function toTimeInput(d: Date): string {
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

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
  const [showBody, setShowBody] = useState(false);
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  // По умолчанию — без повтора. Повторяющееся напоминание, заведённое
  // случайно, раздражает каждый день и его надо идти отключать.
  const [repeat, setRepeat] = useState<RepeatRule | "">("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const when = date && time ? `${date}T${time}` : "";
  const triggerAt = when ? new Date(when) : null;
  const valid = !!title.trim() && !!triggerAt && !Number.isNaN(triggerAt.getTime());

  const setWhen = (d: Date) => {
    setDate(toDateInput(d));
    setTime(toTimeInput(d));
  };
  const quick: { label: string; at: () => Date }[] = [
    { label: t("remind.inHour"), at: () => new Date(Date.now() + 3600_000) },
    {
      label: t("remind.evening"),
      at: () => {
        const d = new Date();
        if (d.getHours() >= 19) d.setDate(d.getDate() + 1);
        d.setHours(19, 0, 0, 0);
        return d;
      },
    },
    {
      label: t("remind.tomorrowMorning"),
      at: () => {
        const d = new Date();
        d.setDate(d.getDate() + 1);
        d.setHours(9, 0, 0, 0);
        return d;
      },
    },
    {
      label: t("remind.inWeek"),
      at: () => {
        const d = new Date();
        d.setDate(d.getDate() + 7);
        d.setHours(9, 0, 0, 0);
        return d;
      },
    },
  ];
  const days = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() + i);
    d.setHours(0, 0, 0, 0);
    return d;
  });

  function submit() {
    if (!valid || !triggerAt) return;
    onCreate({ title: title.trim(), body: body.trim(), triggerAt, repeat });
  }

  const ctaWhen = triggerAt && valid
    ? triggerAt.toLocaleString(dateLocale, { weekday: "long", hour: "2-digit", minute: "2-digit" })
    : null;

  return (
    <div
      className="modal-in fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
      aria-label={t("remind.title")}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="sheet-in flex max-h-[92dvh] w-full max-w-md flex-col overflow-y-auto rounded-t-3xl bg-surface px-4 pb-[max(20px,var(--safe-bottom))] pt-2.5 shadow-xl sm:rounded-3xl sm:pb-5"
      >
        <div className="mx-auto mb-3 h-[5px] w-10 shrink-0 rounded-full bg-muted-active sm:hidden" aria-hidden="true" />
        <h2 className="px-1 text-2xl font-extrabold tracking-tight text-primary">{t("remind.title")}</h2>
        <input
          autoFocus
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t("remind.placeholder")}
          aria-label={t("remind.placeholder")}
          className="mt-3 h-[52px] w-full rounded-2xl bg-muted px-3.5 text-base font-bold text-primary outline-none placeholder:font-semibold placeholder:text-subtle focus:ring-2 focus:ring-brand/40"
        />
        {showBody ? (
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={2}
            placeholder={t("remind.details")}
            className="mt-2 w-full resize-none rounded-2xl bg-muted px-3.5 py-2.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
          />
        ) : (
          <button type="button" onClick={() => setShowBody(true)} className="mt-1.5 self-start px-1 text-xs font-bold text-subtle">
            + {t("remind.details").toLowerCase()}
          </button>
        )}

        <div className="mt-3 grid grid-cols-2 gap-2">
          {quick.map((q) => {
            const d = q.at();
            const active = date === toDateInput(d) && time === toTimeInput(d);
            return (
              <button
                key={q.label}
                type="button"
                onClick={() => setWhen(d)}
                className={`h-[52px] rounded-2xl text-sm font-bold transition-colors ${
                  active ? "border-2 border-brand bg-brand-soft text-brand-text" : "bg-muted text-primary hover:bg-muted-hover"
                }`}
              >
                {q.label}
              </button>
            );
          })}
        </div>

        <div className="mt-4 px-1 text-[11px] font-extrabold uppercase tracking-wider text-subtle">{t("remind.exact")}</div>
        <div className="mt-2 grid grid-cols-7 gap-1">
          {days.map((d) => {
            const v = toDateInput(d);
            const active = date === v;
            return (
              <button
                key={v}
                type="button"
                onClick={() => {
                  setDate(v);
                  if (!time) setTime("09:00");
                }}
                className={`flex h-[62px] flex-col items-center justify-center gap-0.5 rounded-2xl transition-colors ${
                  active ? "bg-accent text-on-accent" : "bg-muted text-primary hover:bg-muted-hover"
                }`}
              >
                <span className="text-[11px] font-bold">{d.toLocaleDateString(dateLocale, { weekday: "short" })}</span>
                <span className="text-lg font-extrabold">{d.getDate()}</span>
              </button>
            );
          })}
        </div>
        <div className="mt-2.5 flex gap-2">
          <input
            type="time"
            lang={dateLocale}
            value={time}
            onChange={(e) => setTime(e.target.value)}
            aria-label="Время"
            className="h-14 flex-1 rounded-2xl bg-muted px-3 text-center text-[22px] font-extrabold tracking-tight text-primary outline-none focus:ring-2 focus:ring-brand/40"
          />
          <input
            type="date"
            lang={dateLocale}
            value={date}
            onChange={(e) => setDate(e.target.value)}
            aria-label="Дата"
            className="h-14 flex-1 rounded-2xl bg-muted px-3 text-sm font-bold text-primary outline-none focus:ring-2 focus:ring-brand/40"
          />
        </div>
        <label className="mt-2 flex h-14 items-center gap-2.5 rounded-2xl bg-muted px-3.5 text-sm font-bold text-primary">
          <Repeat size={16} className="shrink-0 text-subtle" />
          <select
            value={repeat}
            onChange={(e) => setRepeat(e.target.value as RepeatRule | "")}
            className="h-full min-w-0 flex-1 bg-transparent text-sm font-bold outline-none"
          >
            <option value="">{t("remind.noRepeat")}</option>
            {REPEAT_RULES.map((rule) => (
              <option key={rule} value={rule}>
                {REPEAT_LABELS[rule]}
              </option>
            ))}
          </select>
        </label>
        {repeat && (
          // Про это стоит сказать заранее: следующий раз заводится в
          // момент отправки, поэтому "удалить" на пришедшем напоминании
          // серию не остановит, а на ожидающем — остановит.
          <span className="mt-1.5 block px-1 text-[11px] font-semibold text-subtle">
            Напоминание будет приходить {REPEAT_LABELS[repeat]}, пока его не удалить.
          </span>
        )}

        <div className="mt-3.5 flex items-center gap-2.5 rounded-2xl bg-muted px-3.5 py-3">
          <Bell size={18} className="shrink-0 text-brand" />
          <div className="text-[13px] font-bold leading-snug text-primary">{t("remind.channels")}</div>
        </div>

        <button
          onClick={submit}
          disabled={!valid}
          className="mt-3.5 h-14 w-full rounded-2xl bg-accent text-base font-extrabold text-on-accent disabled:opacity-40"
        >
          {ctaWhen ? t("remind.cta", { when: ctaWhen }) : t("remind.ctaEmpty")}
        </button>
      </div>
    </div>
  );
}

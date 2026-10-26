import { useState } from "react";
import { Check, ChevronLeft, History, MoreVertical, Pause, Pill, Play, RotateCcw, Settings2, Trash2 } from "lucide-react";
import { useDeleteItem, useMe, useRoutine, useRoutineDoseAction, useSpaces, useUpdateRoutine } from "../api/hooks";
import type { RoutineDose } from "../api/types";
import { dayOfCourse, deferredNames, humanMinutes, lateMinutes, sameLocalDay, waitingMinutes } from "../lib/routineFormat";
import ConfirmDialog from "./ConfirmDialog";
import DoseDoneSheet from "./DoseDoneSheet";
import RoutineSheet from "./RoutineSheet";
import Spinner from "./Spinner";
import VersionHistoryPanel from "./VersionHistoryPanel";
import { dateLocale, t } from "../i18n";

// Экран рутины (макет «Рутина: заметка», 26.10): шапка как у заметки,
// тёмная карточка «Сегодня» с приёмами и кнопкой «Дал», полоса курса,
// журнал. Настройки — отдельной шторкой (RoutineSheet), отметка приёма —
// своей (DoseDoneSheet), чтобы время приёма не терялось одним тапом.

function timeOf(value: string): string {
  return new Date(value).toLocaleTimeString(dateLocale, { hour: "2-digit", minute: "2-digit" });
}

function dayLabel(value: string, now: Date): string {
  const d = new Date(value);
  if (sameLocalDay(d, now)) return t("routine.today").toLowerCase();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameLocalDay(d, yesterday)) return dateLocale.startsWith("ru") ? "вчера" : "yesterday";
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (sameLocalDay(d, tomorrow)) return dateLocale.startsWith("ru") ? "завтра" : "tomorrow";
  return d.toLocaleDateString(dateLocale, { day: "numeric", month: "short" });
}

function DoseBadge({ dose }: { dose: RoutineDose }) {
  if (dose.status === "done") {
    const late = lateMinutes(dose);
    return late > 0 ? (
      <span className="rounded-full bg-warning/15 px-2.5 py-1 text-xs font-extrabold text-warning">{t("routine.lateBy", { n: late })}</span>
    ) : (
      <span className="rounded-full bg-lime/60 px-2.5 py-1 text-xs font-extrabold text-on-lime">{t("routine.onTime")}</span>
    );
  }
  if (dose.status === "skipped") return <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-extrabold text-subtle">{t("routine.skipped")}</span>;
  return <span className="rounded-full bg-muted px-2.5 py-1 text-xs font-extrabold text-subtle">{t("routine.missed")}</span>;
}

export default function RoutineEditor({ itemId, onDeleted, onBack }: { itemId: string; onDeleted: () => void; onBack: () => void }) {
  const { data: routine } = useRoutine(itemId);
  const { data: me } = useMe();
  const { data: spaces } = useSpaces();
  const update = useUpdateRoutine(itemId);
  const deleteItem = useDeleteItem(routine?.space_id);
  const act = useRoutineDoseAction();
  const [menuOpen, setMenuOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [doneFor, setDoneFor] = useState<RoutineDose | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  if (!routine) {
    return (
      <div className="flex h-full items-center justify-center text-subtle">
        <Spinner />
      </div>
    );
  }

  const now = new Date();
  const space = spaces?.find((s) => s.id === routine.space_id);
  const pending = routine.doses.find((d) => d.status === "pending") ?? null;
  // День закрытого приёма — когда дали на самом деле, а не план: вечером
  // дали «завтрашнюю утреннюю» заранее — она сегодняшняя.
  const dayOf = (d: RoutineDose) => new Date(d.status === "done" && d.done_at ? d.done_at : d.planned_at);
  const todayClosed = routine.doses.filter((d) => d.status !== "pending" && sameLocalDay(dayOf(d), now));
  const journal = routine.doses
    .filter((d) => d.status !== "pending" && !sameLocalDay(dayOf(d), now))
    .slice(-30)
    .reverse();
  const lastClosed = [...routine.doses].filter((d) => d.status !== "pending").pop() ?? null;
  const course = dayOfCourse(routine, now);
  const subtitle = [routine.subject, routine.dose, routine.schedule_text, routine.ends_on ? `${t("routine.to")} ${new Date(routine.ends_on + "T00:00:00").toLocaleDateString(dateLocale, { day: "numeric", month: "short" })}` : null]
    .filter(Boolean)
    .join(" · ");
  const busy = act.isPending;

  const quick = (dose: RoutineDose, action: "defer" | "skip" | "snooze", minutes?: number) =>
    act.mutate({ routineId: routine.id, doseId: dose.id, action, body: minutes ? { minutes } : undefined });

  const pendingStatus = (dose: RoutineDose) => {
    const names = deferredNames(dose, me?.id);
    const parts: string[] = [];
    const waiting = waitingMinutes(dose, now);
    if (waiting > 0) parts.push(t("routine.waiting", { n: humanMinutes(waiting, dateLocale) }));
    else {
      const until = Math.round((new Date(dose.planned_at).getTime() - now.getTime()) / 60_000);
      parts.push(t("routine.inTime", { n: humanMinutes(until, dateLocale) }));
    }
    if (dose.deferred_by.some((d) => d.id === me?.id)) parts.push(t("routine.youDeferred"));
    else if (names.length) parts.push(t("routine.deferredBy", { names: names.join(", ") }));
    return parts.join(" · ");
  };

  const menuItem = "flex min-h-11 w-full items-center gap-2.5 px-4 text-left text-sm font-semibold text-secondary hover:bg-muted";

  return (
    <div className="flex h-full">
      <div className="relative flex min-w-0 flex-1 flex-col overflow-y-auto">
        <div className="flex items-center gap-2 p-3 lg:border-b">
          <button onClick={onBack} aria-label={t("nav.back")} className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card lg:hidden">
            <ChevronLeft size={20} strokeWidth={2.4} />
          </button>
          <div className="min-w-0 flex-1 truncate pl-1 text-[13px] font-bold text-subtle">
            {space ? `${space.name} › ` : ""}
            {t("routine.kind")}
          </div>
          <button onClick={() => setSettingsOpen(true)} title={t("routine.settings")} className="hidden h-9 items-center gap-1.5 rounded-xl px-3 text-sm font-bold text-secondary hover:bg-muted lg:flex">
            <Settings2 size={16} /> {t("routine.edit")}
          </button>
          <button onClick={() => setShowHistory((v) => !v)} title={t("routine.history")} className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl text-subtle hover:bg-muted hover:text-secondary lg:flex">
            <History size={16} />
          </button>
          <button onClick={() => setConfirmingDelete(true)} title={t("routine.delete")} className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl text-subtle hover:bg-muted hover:text-danger lg:flex">
            <Trash2 size={16} />
          </button>
          <div className="relative shrink-0 lg:hidden">
            <button onClick={() => setMenuOpen((v) => !v)} aria-label={t("routine.settings")} className="flex h-11 w-11 items-center justify-center rounded-2xl bg-surface text-primary shadow-card">
              <MoreVertical size={20} />
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setMenuOpen(false)} />
                <div className="absolute right-0 top-full z-30 mt-1 w-60 overflow-hidden rounded-2xl border bg-surface py-1.5 shadow-lg">
                  <button onClick={() => { setSettingsOpen(true); setMenuOpen(false); }} className={menuItem}>
                    <Settings2 size={14} /> {t("routine.settings")}
                  </button>
                  <button onClick={() => { update.mutate({ paused: !routine.paused }); setMenuOpen(false); }} className={menuItem}>
                    {routine.paused ? <Play size={14} /> : <Pause size={14} />} {routine.paused ? t("routine.resume") : t("routine.pause")}
                  </button>
                  {lastClosed && (
                    <button onClick={() => { act.mutate({ routineId: routine.id, doseId: lastClosed.id, action: "reopen" }); setMenuOpen(false); }} className={menuItem}>
                      <RotateCcw size={14} /> {t("routine.reopen")}
                    </button>
                  )}
                  <button onClick={() => { setShowHistory((v) => !v); setMenuOpen(false); }} className={menuItem}>
                    <History size={14} /> {t("routine.history")}
                  </button>
                  <button onClick={() => { setConfirmingDelete(true); setMenuOpen(false); }} className="flex min-h-11 w-full items-center gap-2.5 px-4 text-left text-sm font-bold text-danger hover:bg-danger-soft">
                    <Trash2 size={14} /> {t("routine.delete")}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3.5 px-5 pt-2 lg:px-6 lg:pt-4">
          <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-[18px] bg-brand-soft text-brand-text">
            <Pill size={28} strokeWidth={2.2} />
          </span>
          <div className="min-w-0">
            <h1 className="text-[26px] font-extrabold leading-tight tracking-tight text-primary lg:text-[30px]">{routine.title}</h1>
            {subtitle && <div className="mt-0.5 text-[13px] font-semibold text-subtle">{subtitle}</div>}
          </div>
        </div>

        {routine.paused && <div className="mx-5 mt-3 rounded-2xl bg-warning/15 px-3.5 py-2.5 text-[13px] font-bold text-warning lg:mx-6">{t("routine.paused")}</div>}
        {routine.status === "finished" && !pending && <div className="mx-5 mt-3 rounded-2xl bg-lime/60 px-3.5 py-2.5 text-[13px] font-bold text-on-lime lg:mx-6">{t("routine.finished")}</div>}

        <section aria-label={t("routine.today")} className="mx-5 mt-4 rounded-[22px] bg-nav p-4 text-nav-text lg:mx-6 lg:max-w-2xl">
          <div className="flex items-center justify-between text-[12px] font-extrabold uppercase tracking-wider text-nav-muted">
            <span>{t("routine.today")}, {now.toLocaleDateString(dateLocale, { weekday: "short", day: "numeric", month: "short" })}</span>
            {course && <span>{t("routine.dayOf", course)}</span>}
          </div>
          {todayClosed.map((dose) => (
            <div key={dose.id} className="mt-3.5 flex items-center gap-3 border-b border-nav-text/10 pb-3 last:border-0">
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${dose.status === "done" ? "bg-lime text-on-lime" : "border-2 border-nav-muted/60"}`}>
                {dose.status === "done" && <Check size={16} strokeWidth={3} />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[17px] font-extrabold">{timeOf(dose.planned_at)}</div>
                <div className="truncate text-[13px] font-semibold text-nav-muted">
                  {dose.status === "done" && dose.done_at
                    ? t("routine.gaveAt", { name: dose.done_by_name ?? "", time: timeOf(dose.done_at) })
                    : dose.status === "skipped"
                      ? t("routine.skipped")
                      : t("routine.missed")}
                </div>
              </div>
              {dose.status === "done" && lateMinutes(dose) > 0 && <span className="rounded-full bg-warning/25 px-2.5 py-1 text-xs font-extrabold text-nav-text">{t("routine.lateBy", { n: lateMinutes(dose) })}</span>}
            </div>
          ))}
          {pending ? (
            <>
              <div className="mt-3.5 flex items-center gap-3">
                <span className="flex h-8 w-8 shrink-0 rounded-full border-2 border-nav-muted/60" />
                <div className="min-w-0 flex-1">
                  <div className="text-[17px] font-extrabold">
                    {!sameLocalDay(new Date(pending.planned_at), now) && <span className="mr-1.5 text-[13px] font-bold text-nav-muted">{t("routine.next")} · {dayLabel(pending.planned_at, now)},</span>}
                    {timeOf(pending.planned_at)}
                  </div>
                  <div className={`truncate text-[13px] font-semibold ${waitingMinutes(pending, now) > 0 ? "text-warning" : "text-nav-muted"}`}>{pendingStatus(pending)}</div>
                </div>
                <button onClick={() => setDoneFor(pending)} disabled={busy} className="h-11 rounded-full bg-lime px-5 text-[15px] font-extrabold text-on-lime disabled:opacity-60">
                  {t("routine.given")}
                </button>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <button onClick={() => quick(pending, "snooze", 30)} disabled={busy} className="h-9 rounded-full bg-nav-text/10 px-3 text-xs font-bold text-nav-text disabled:opacity-60">{t("routine.plus30")}</button>
                <button onClick={() => quick(pending, "snooze", 60)} disabled={busy} className="h-9 rounded-full bg-nav-text/10 px-3 text-xs font-bold text-nav-text disabled:opacity-60">{t("routine.plus60")}</button>
                {!pending.deferred_by.some((d) => d.id === me?.id) && (
                  <button onClick={() => quick(pending, "defer")} disabled={busy} className="h-9 rounded-full bg-nav-text/10 px-3 text-xs font-bold text-nav-text disabled:opacity-60">{t("routine.notMe")}</button>
                )}
                <button onClick={() => quick(pending, "skip")} disabled={busy} className="h-9 rounded-full bg-nav-text/10 px-3 text-xs font-bold text-nav-muted disabled:opacity-60">{t("routine.skip")}</button>
              </div>
            </>
          ) : (
            todayClosed.length === 0 && <div className="mt-3 text-[14px] font-semibold text-nav-muted">{t("routine.nothingOpen")}</div>
          )}
        </section>

        <div className="mx-5 mt-3 lg:mx-6 lg:max-w-2xl">
          {course && (
            <div className="h-1.5 overflow-hidden rounded-full bg-muted">
              <div className="h-full rounded-full bg-brand transition-[width]" style={{ width: `${Math.round((course.day / course.total) * 100)}%` }} />
            </div>
          )}
          <div className="mt-1.5 text-[12px] font-semibold text-subtle">{t("routine.stats", { done: routine.stats.done, late: routine.stats.late, missed: routine.stats.missed })}</div>
        </div>

        {journal.length > 0 && (
          <div className="mx-5 mt-4 pb-28 lg:mx-6 lg:max-w-2xl lg:pb-8">
            <h2 className="text-lg font-extrabold tracking-tight text-primary">{t("routine.journal")}</h2>
            <div className="mt-2 flex flex-col gap-2">
              {journal.map((dose) => (
                <div key={dose.id} className="flex items-center gap-3 rounded-2xl bg-muted px-3.5 py-3">
                  <div className="w-16 shrink-0 text-[13px] font-bold text-subtle">{dayLabel(dayOf(dose).toISOString(), now)}</div>
                  <div className="min-w-0 flex-1 truncate text-[15px] font-extrabold text-primary">
                    {dose.status === "done" && dose.done_at ? `${timeOf(dose.done_at)} · ${dose.done_by_name ?? ""}` : timeOf(dose.planned_at)}
                  </div>
                  <DoseBadge dose={dose} />
                </div>
              ))}
            </div>
          </div>
        )}
        {journal.length === 0 && <div className="pb-28 lg:pb-8" />}

        <div className="pointer-events-none fixed inset-x-0 bottom-[calc(var(--safe-bottom)+92px)] z-10 flex justify-center lg:hidden">
          <button onClick={() => setSettingsOpen(true)} className="pointer-events-auto flex h-[52px] items-center gap-2 rounded-full bg-nav px-6 text-[15px] font-extrabold text-nav-text shadow-float">
            <Settings2 size={18} strokeWidth={2.4} /> {t("routine.edit")}
          </button>
        </div>
      </div>

      {showHistory && <VersionHistoryPanel itemId={itemId} onClose={() => setShowHistory(false)} />}
      {settingsOpen && space && (
        <RoutineSheet space={space} routine={routine} onSaved={() => setSettingsOpen(false)} onClose={() => setSettingsOpen(false)} />
      )}
      {doneFor && <DoseDoneSheet routine={routine} dose={doneFor} onClose={() => setDoneFor(null)} />}
      {confirmingDelete && (
        <ConfirmDialog
          title={t("routine.deleteConfirm")}
          danger
          onConfirm={() => {
            setConfirmingDelete(false);
            deleteItem.mutate(routine.id, { onSuccess: onDeleted });
          }}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}
    </div>
  );
}

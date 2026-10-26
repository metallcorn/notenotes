import { FormEvent, useEffect, useState } from "react";
import { Send, X } from "lucide-react";
import { useCreateRoutine, useMe, useSpaceMembers, useUpdateRoutine } from "../api/hooks";
import type { Routine, RoutineInput, Space } from "../api/types";
import Spinner from "./Spinner";
import { t } from "../i18n";

// Шторка «Новая рутина» / «Настройки рутины» (макет «Рутина: создать»,
// 26.10): название, для кого, что и сколько, «по часам» с временами и
// зазором или «по интервалу», курс, кому напоминать и как часто повторять.

const GAP_OPTIONS = [0, 240, 360, 480, 600, 720];
const EVERY_OPTIONS = [240, 360, 480, 720, 1440, 2880];
const NAG_OPTIONS = [0, 15, 30, 60];

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
function todayInput(): string {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
function hoursLabel(minutes: number): string {
  return minutes % 1440 === 0 ? t("routine.days", { n: minutes / 1440 }) : t("routine.hours", { n: minutes / 60 });
}

const input =
  "h-12 w-full rounded-2xl border-0 bg-muted px-3.5 text-[15px] font-bold text-primary outline-none placeholder:font-semibold placeholder:text-subtle focus:ring-2 focus:ring-brand/40";
const label = "mt-4 px-1 text-[11px] font-extrabold uppercase tracking-wider text-subtle";
const chip = (active: boolean) =>
  `h-11 rounded-full px-4 text-sm font-bold transition-colors ${
    active ? "border-2 border-brand bg-brand-soft text-brand-text" : "border-2 border-transparent bg-muted text-primary hover:bg-muted-hover"
  }`;

export default function RoutineSheet({
  space,
  folderId,
  routine,
  onSaved,
  onClose,
}: {
  space: Space;
  folderId?: string | null;
  routine?: Routine;
  onSaved: (routine: Routine) => void;
  onClose: () => void;
}) {
  const { data: me } = useMe();
  const { data: members } = useSpaceMembers(space.id);
  const create = useCreateRoutine();
  const update = useUpdateRoutine(routine?.id);

  const [title, setTitle] = useState(routine?.title ?? "");
  const [subject, setSubject] = useState(routine?.subject ?? "");
  const [dose, setDose] = useState(routine?.dose ?? "");
  const [mode, setMode] = useState<"times" | "interval">(routine?.schedule.mode ?? "times");
  const [times, setTimes] = useState<string[]>(routine?.schedule.times?.length ? routine.schedule.times : ["08:00", "20:00"]);
  const [newTime, setNewTime] = useState("");
  const [minGap, setMinGap] = useState(routine?.schedule.min_gap_minutes ?? 0);
  const [every, setEvery] = useState(routine?.schedule.every_minutes ?? 1440);
  const [firstAt, setFirstAt] = useState(routine?.schedule.first_at ?? "");
  const [startsOn, setStartsOn] = useState(routine?.starts_on ?? todayInput());
  const [endsOn, setEndsOn] = useState(routine?.ends_on ?? "");
  const [notify, setNotify] = useState<"space" | "self">(routine?.notify ?? "space");
  const [nag, setNag] = useState(routine?.nag_minutes ?? 30);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const busy = create.isPending || update.isPending;
  const valid = title.trim().length > 0 && (mode === "times" ? times.length > 0 : every > 0);

  function addTime() {
    if (!/^\d{2}:\d{2}$/.test(newTime) || times.includes(newTime)) return;
    setTimes([...times, newTime].sort());
    setNewTime("");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!valid || busy) return;
    setError(null);
    const payload: RoutineInput = {
      title: title.trim(),
      subject: subject.trim(),
      dose: dose.trim(),
      schedule: {
        mode,
        times: mode === "times" ? times : [],
        every_minutes: mode === "interval" ? every : null,
        min_gap_minutes: mode === "times" ? minGap : 0,
        first_at: mode === "interval" && firstAt ? firstAt : null,
      },
      starts_on: startsOn || null,
      ends_on: endsOn || null,
      notify,
      nag_minutes: nag,
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };
    try {
      const saved = routine
        ? await update.mutateAsync(payload)
        : await create.mutateAsync({ ...payload, space_id: space.id, folder_id: folderId ?? null });
      onSaved(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const subjectChips = [
    t("routine.me"),
    ...(members ?? []).filter((m) => m.user_id !== me?.id).map((m) => m.name || m.username),
  ];

  return (
    <div
      className="modal-in fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={routine ? t("routine.settings") : t("routine.new")}
    >
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="sheet-in flex max-h-[94dvh] w-full max-w-md flex-col rounded-t-3xl bg-surface shadow-xl sm:rounded-3xl"
      >
        <div className="mx-auto mt-2.5 h-[5px] w-10 shrink-0 rounded-full bg-muted-active sm:hidden" aria-hidden="true" />
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-3 pt-3">
          <div className="flex items-center justify-between gap-2 px-1">
            <h2 className="text-2xl font-extrabold tracking-tight text-primary">{routine ? t("routine.settings") : t("routine.new")}</h2>
            <span className="truncate rounded-full bg-brand-soft px-2.5 py-1 text-xs font-extrabold text-brand-text">{space.name}</span>
          </div>

          <label className="mt-3 block">
            <span className="sr-only">{t("routine.titlePlaceholder")}</span>
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder={t("routine.titlePlaceholder")} className={`${input} text-[17px] font-extrabold`} autoFocus={!routine} />
          </label>

          <div className={label}>{t("routine.subject")}</div>
          <div className="mt-2 flex flex-wrap gap-2">
            {subjectChips.map((name) => (
              <button key={name} type="button" onClick={() => setSubject(name)} className={chip(subject.trim() === name)}>
                {name}
              </button>
            ))}
          </div>
          <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder={t("routine.subjectPlaceholder")} className={`${input} mt-2 h-11`} />

          <div className={label}>{t("routine.dose")}</div>
          <input value={dose} onChange={(e) => setDose(e.target.value)} placeholder={t("routine.dosePlaceholder")} className={`${input} mt-2 h-11 font-semibold`} />

          <div className={label}>{t("routine.howOften")}</div>
          <div className="mt-2 grid grid-cols-2 gap-1 rounded-2xl bg-muted-active/60 p-1">
            {(["times", "interval"] as const).map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => setMode(m)}
                className={`h-10 rounded-xl text-sm font-extrabold transition-colors ${mode === m ? "bg-surface text-primary shadow-card" : "text-secondary"}`}
              >
                {m === "times" ? t("routine.byTimes") : t("routine.byInterval")}
              </button>
            ))}
          </div>
          {mode === "times" ? (
            <>
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                {times.map((tm) => (
                  <span key={tm} className="flex h-12 items-center gap-1 rounded-2xl bg-nav pl-4 pr-2 text-xl font-extrabold tracking-tight text-lime">
                    {tm}
                    <button type="button" aria-label={`${t("nav.back")} ${tm}`} onClick={() => setTimes(times.filter((x) => x !== tm))} className="flex h-8 w-8 items-center justify-center rounded-xl text-nav-muted hover:text-nav-text">
                      <X size={14} />
                    </button>
                  </span>
                ))}
                <span className="flex h-12 items-center gap-1 rounded-2xl border-[1.5px] border-dashed border-strong px-2">
                  <input type="time" value={newTime} onChange={(e) => setNewTime(e.target.value)} aria-label={t("routine.addTime")} className="w-[92px] border-0 bg-transparent text-sm font-bold text-primary outline-none" />
                  <button type="button" onClick={addTime} disabled={!newTime} className="h-8 rounded-xl px-2 text-sm font-bold text-brand-text disabled:opacity-40">
                    {t("routine.addTime")}
                  </button>
                </span>
              </div>
              <div className="mt-2.5 flex items-center justify-between gap-2 px-1 text-[13px] font-semibold text-subtle">
                <span>{t("routine.minGap")}</span>
                <select value={minGap} onChange={(e) => setMinGap(Number(e.target.value))} className="h-9 rounded-xl bg-muted px-2 text-sm font-bold text-primary outline-none">
                  {GAP_OPTIONS.map((g) => (
                    <option key={g} value={g}>
                      {g === 0 ? t("routine.noGap") : hoursLabel(g)}
                    </option>
                  ))}
                </select>
              </div>
              {minGap > 0 && <div className="mt-1 px-1 text-[12px] font-semibold text-subtle">{t("routine.gapHint")}</div>}
            </>
          ) : (
            <div className="mt-2.5 grid grid-cols-2 gap-2">
              <label className="flex h-12 items-center justify-between rounded-2xl bg-muted px-3.5 text-sm font-bold text-primary">
                {t("routine.every")}
                <select value={every} onChange={(e) => setEvery(Number(e.target.value))} className="bg-transparent text-right font-extrabold outline-none">
                  {EVERY_OPTIONS.map((m) => (
                    <option key={m} value={m}>
                      {hoursLabel(m)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex h-12 items-center justify-between gap-2 rounded-2xl bg-muted px-3.5 text-sm font-bold text-primary">
                <span className="truncate">{t("routine.firstAt")}</span>
                <input type="time" value={firstAt} onChange={(e) => setFirstAt(e.target.value)} className="w-[92px] bg-transparent text-right font-extrabold outline-none" />
              </label>
            </div>
          )}

          <div className={label}>{t("routine.course")}</div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <label className="flex h-12 items-center gap-2 rounded-2xl bg-muted px-3.5 text-sm font-bold text-primary">
              {t("routine.from")}
              <input type="date" value={startsOn} onChange={(e) => setStartsOn(e.target.value)} className="min-w-0 flex-1 bg-transparent text-right font-extrabold outline-none" />
            </label>
            <label className="flex h-12 items-center gap-2 rounded-2xl bg-muted px-3.5 text-sm font-bold text-primary">
              {t("routine.to")}
              <input type="date" value={endsOn} min={startsOn || undefined} onChange={(e) => setEndsOn(e.target.value)} placeholder={t("routine.openEnded")} className="min-w-0 flex-1 bg-transparent text-right font-extrabold outline-none" />
            </label>
          </div>

          <div className={label}>{t("routine.notify")}</div>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {(["space", "self"] as const).map((n) => (
              <button key={n} type="button" onClick={() => setNotify(n)} className={`${chip(notify === n)} h-12 rounded-2xl`}>
                {n === "space" ? t("routine.notifySpace") : t("routine.notifySelf")}
              </button>
            ))}
          </div>
          <div className="mt-2 flex items-center justify-between gap-2 px-1 text-[13px] font-semibold text-subtle">
            <span>{t("routine.nag")}</span>
            <select value={nag} onChange={(e) => setNag(Number(e.target.value))} className="h-9 rounded-xl bg-muted px-2 text-sm font-bold text-primary outline-none">
              {NAG_OPTIONS.map((n) => (
                <option key={n} value={n}>
                  {n === 0 ? t("routine.nagOff") : t("routine.nagEvery", { n })}
                </option>
              ))}
            </select>
          </div>
          <div className="mt-2 flex items-center gap-2.5 rounded-2xl bg-muted px-3.5 py-3 text-[13px] font-bold leading-snug text-primary">
            <Send size={18} className="shrink-0 text-link" />
            {t("routine.nagHint")}
          </div>
          {error && <div className="mt-2 rounded-2xl bg-danger-soft px-3.5 py-2.5 text-sm font-semibold text-danger">{error}</div>}
        </div>
        <div className="shrink-0 px-4 pb-[max(16px,var(--safe-bottom))] pt-2 sm:pb-4">
          <button type="submit" disabled={!valid || busy} className="flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-nav text-base font-extrabold text-nav-text disabled:opacity-50">
            {busy ? <Spinner size={18} /> : null}
            {routine ? t("routine.save") : t("routine.create")}
          </button>
        </div>
      </form>
    </div>
  );
}

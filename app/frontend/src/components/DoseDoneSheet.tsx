import { useEffect, useState } from "react";
import { AlarmClock, Pill } from "lucide-react";
import { useMe, useRoutineDoseAction, useSpaceMembers } from "../api/hooks";
import type { Routine, RoutineDose } from "../api/types";
import { humanMinutes } from "../lib/routineFormat";
import Spinner from "./Spinner";
import { dateLocale, t } from "../i18n";

// Шторка «Отметить приём» (макет «Рутина: отметить приём», 26.10): когда
// дал (сейчас / по плану / другое время), кто дал, и рядом — «делает не
// я» и «пропустить». Время важно по-настоящему: от него считается
// следующий приём по интервалу и зазор (app/routine_schedule.py).

function pad(n: number): string {
  return String(n).padStart(2, "0");
}
function toLocalInput(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function DoseDoneSheet({ routine, dose, onClose }: { routine: Routine; dose: RoutineDose; onClose: () => void }) {
  const { data: me } = useMe();
  const { data: members } = useSpaceMembers(routine.notify === "space" ? routine.space_id : undefined);
  const action = useRoutineDoseAction();
  const [whenMode, setWhenMode] = useState<"now" | "planned" | "other">("now");
  const [other, setOther] = useState(toLocalInput(new Date()));
  const [who, setWho] = useState<string | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const planned = new Date(dose.planned_at);
  const now = new Date();
  const at = whenMode === "now" ? now : whenMode === "planned" ? planned : new Date(other);
  const atValid = !Number.isNaN(at.getTime()) && at.getTime() <= now.getTime() + 5 * 60_000;
  const time = (d: Date) => d.toLocaleTimeString(dateLocale, { hour: "2-digit", minute: "2-digit" });
  const lateMin = Math.round((at.getTime() - planned.getTime()) / 60_000);
  const busy = action.isPending;

  async function run(kind: "done" | "defer" | "skip") {
    if (busy) return;
    setError(null);
    try {
      await action.mutateAsync({
        routineId: routine.id,
        doseId: dose.id,
        action: kind,
        body: kind === "done" ? { at: at.toISOString(), ...(who && who !== me?.id ? { by: who } : {}) } : undefined,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  const whenOptions: { key: "now" | "planned" | "other"; big: string; small: string }[] = [
    { key: "now", big: time(now), small: t("routine.now") },
    { key: "planned", big: time(planned), small: t("routine.planned") },
    { key: "other", big: "…", small: t("routine.other") },
  ];

  return (
    <div className="modal-in fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4" onClick={onClose} role="dialog" aria-modal="true" aria-label={t("routine.given")}>
      <div onClick={(e) => e.stopPropagation()} className="sheet-in w-full max-w-md rounded-t-3xl bg-surface px-4 pb-[max(20px,var(--safe-bottom))] pt-2.5 shadow-xl sm:rounded-3xl sm:pb-5">
        <div className="mx-auto mb-3 h-[5px] w-10 rounded-full bg-muted-active sm:hidden" aria-hidden="true" />
        <div className="flex items-center gap-3 px-1">
          <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand-text">
            <Pill size={22} strokeWidth={2.2} />
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-[22px] font-extrabold tracking-tight text-primary">{routine.title}</h2>
            <div className="truncate text-[13px] font-semibold text-subtle">
              {t("routine.doseShort")} {time(planned)}
              {routine.dose ? ` · ${routine.dose}` : ""}
            </div>
          </div>
        </div>

        <div className="mt-4 px-1 text-[11px] font-extrabold uppercase tracking-wider text-subtle">{t("routine.whenGiven")}</div>
        <div className="mt-2 grid grid-cols-3 gap-2">
          {whenOptions.map((o) => (
            <button
              key={o.key}
              type="button"
              onClick={() => setWhenMode(o.key)}
              className={`flex h-[60px] flex-col items-center justify-center rounded-2xl border-2 transition-colors ${
                whenMode === o.key ? "border-brand bg-brand-soft text-brand-text" : "border-transparent bg-muted text-primary"
              }`}
            >
              <span className="text-lg font-extrabold leading-tight">{o.big}</span>
              <span className="text-[11px] font-bold opacity-80">{o.small}</span>
            </button>
          ))}
        </div>
        {whenMode === "other" && (
          <input type="datetime-local" value={other} max={toLocalInput(now)} onChange={(e) => setOther(e.target.value)} className="mt-2 h-11 w-full rounded-2xl border-0 bg-muted px-3.5 text-[15px] font-bold text-primary outline-none" />
        )}

        {members && members.length > 1 && (
          <>
            <div className="mt-4 px-1 text-[11px] font-extrabold uppercase tracking-wider text-subtle">{t("routine.who")}</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {members.map((m) => {
                const active = (who ?? me?.id) === m.user_id;
                return (
                  <button
                    key={m.user_id}
                    type="button"
                    onClick={() => setWho(m.user_id)}
                    className={`h-11 rounded-full px-4 text-sm font-bold transition-colors ${
                      active ? "border-2 border-brand bg-brand-soft text-brand-text" : "border-2 border-transparent bg-muted text-primary"
                    }`}
                  >
                    {m.user_id === me?.id ? t("routine.me") : m.name || m.username}
                  </button>
                );
              })}
            </div>
          </>
        )}

        {atValid && lateMin > 15 && (
          <div className="mt-4 flex items-start gap-2.5 rounded-2xl bg-warning/15 px-3.5 py-3 text-[13px] font-bold leading-snug text-warning">
            <AlarmClock size={18} className="mt-0.5 shrink-0" />
            {t("routine.lateHint", { n: humanMinutes(lateMin, dateLocale) })}
          </div>
        )}
        {error && <div className="mt-3 rounded-2xl bg-danger-soft px-3.5 py-2.5 text-sm font-semibold text-danger">{error}</div>}

        <button type="button" onClick={() => run("done")} disabled={busy || !atValid} className="mt-4 flex h-14 w-full items-center justify-center gap-2 rounded-2xl bg-nav text-base font-extrabold text-nav-text disabled:opacity-50">
          {busy ? <Spinner size={18} /> : null}
          {t("routine.markDone", { time: atValid ? time(at) : "—" })}
        </button>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <button type="button" onClick={() => run("defer")} disabled={busy} className="h-12 rounded-2xl border-[1.5px] border-strong text-sm font-extrabold text-primary disabled:opacity-50">
            {t("routine.notMe")}
          </button>
          <button type="button" onClick={() => run("skip")} disabled={busy} className="h-12 rounded-2xl bg-muted text-sm font-bold text-subtle disabled:opacity-50">
            {t("routine.skip")}
          </button>
        </div>
        <div className="mt-2.5 px-1 text-[12px] font-semibold leading-snug text-subtle">{t("routine.notMeHint")}</div>
      </div>
    </div>
  );
}

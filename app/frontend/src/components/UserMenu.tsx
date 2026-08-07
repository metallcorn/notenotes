import { useState } from "react";
import { LogOut, MessageSquare, Settings, User as UserIcon } from "lucide-react";
import { useLogout, useMe } from "../api/hooks";
import { OPEN_FEEDBACK_EVENT } from "./FeedbackWidget";
import SettingsModal from "./SettingsModal";

export default function UserMenu() {
  const [open, setOpen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const { data: me } = useMe();
  const logout = useLogout();

  return (
    <div className="relative flex-1">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded px-1 py-1 text-left hover:bg-slate-100"
      >
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-medium text-white">
          {(me?.name || "?").slice(0, 1).toUpperCase()}
        </span>
        <span className="truncate text-xs text-slate-600">{me?.name}</span>
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="absolute bottom-full left-0 z-30 mb-1 w-64 max-w-[calc(100vw-1.5rem)] rounded border bg-white shadow-lg">
            <div className="border-b px-3 py-2">
              <div className="flex items-center gap-2">
                <UserIcon size={14} className="text-slate-400" />
                <span className="text-sm font-medium text-slate-900">{me?.name}</span>
              </div>
              <div className="mt-0.5 text-xs text-slate-400">@{me?.username}</div>
            </div>
            <div className="border-b px-3 py-2">
              <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">Настройки</div>
              <div className="flex items-center justify-between py-1 text-sm text-slate-400">
                <span>Язык интерфейса</span>
                <span title="Скоро — пока только русский">Русский</span>
              </div>
            </div>
            <button
              onClick={() => {
                setShowSettings(true);
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 border-b px-3 py-2 text-left text-sm text-slate-600 hover:bg-slate-50"
            >
              <Settings size={14} />
              Настройки ассистента
            </button>
            <button
              onClick={() => {
                window.dispatchEvent(new Event(OPEN_FEEDBACK_EVENT));
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 border-b px-3 py-2 text-left text-sm text-slate-600 hover:bg-slate-50"
            >
              <MessageSquare size={14} />
              Оставить отзыв
            </button>
            <button
              onClick={() => logout.mutate()}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-600 hover:bg-slate-50"
            >
              <LogOut size={14} />
              Выйти
            </button>
          </div>
        </>
      )}
      {showSettings && <SettingsModal onClose={() => setShowSettings(false)} />}
    </div>
  );
}

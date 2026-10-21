import { useEffect, useState } from "react";
import { LogOut, MessageSquare, Monitor, Moon, Settings, Sun, User as UserIcon } from "lucide-react";
import { useLogout, useMe } from "../api/hooks";
import { applyTheme, watchSystemTheme } from "../lib/theme";
import { uiStorage, type Theme } from "../lib/storage";
import { OPEN_FEEDBACK_EVENT } from "./FeedbackWidget";
import SettingsModal from "./SettingsModal";

const THEME_OPTIONS: { value: Theme; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Светлая", Icon: Sun },
  { value: "dark", label: "Тёмная", Icon: Moon },
  { value: "system", label: "Системная", Icon: Monitor },
];

// compact — только аватар (шапка «Главной» на телефоне, макет 21.10),
// placement — куда раскрывать меню: вверх из футера сайдбара, вниз из
// шапки. Одно меню на оба места, чтобы пункты не разъехались.
export default function UserMenu({
  compact = false,
  placement = "up",
}: {
  compact?: boolean;
  placement?: "up" | "down";
} = {}) {
  const [open, setOpen] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [theme, setThemeState] = useState<Theme>(() => uiStorage.getTheme());
  const { data: me } = useMe();
  const logout = useLogout();

  // Реальная просьба: режим "Системная" должен живо реагировать на смену
  // темы KDE/ОС, пока приложение открыто — не только при следующей
  // перезагрузке страницы.
  useEffect(() => {
    if (theme !== "system") return;
    return watchSystemTheme(() => applyTheme("system"));
  }, [theme]);

  function handleSetTheme(next: Theme) {
    uiStorage.setTheme(next);
    applyTheme(next);
    setThemeState(next);
  }

  return (
    <div className={compact ? "relative" : "relative flex-1"}>
      {compact ? (
        <button
          onClick={() => setOpen((v) => !v)}
          aria-label="Профиль и настройки"
          title="Профиль и настройки"
          className="flex h-11 w-11 items-center justify-center rounded-full bg-nav text-base font-extrabold text-lime"
        >
          {(me?.name || "?").slice(0, 1).toUpperCase()}
        </button>
      ) : (
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left hover:bg-muted-hover"
        >
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-nav text-xs font-extrabold text-lime">
            {(me?.name || "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="truncate text-sm font-semibold text-primary">{me?.name}</span>
        </button>
      )}
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div
            className={`absolute z-30 w-64 max-w-[calc(100vw-1.5rem)] overflow-hidden rounded-2xl border border-default bg-surface shadow-lg ${
              placement === "up" ? "bottom-full left-0 mb-1" : "right-0 top-full mt-1"
            }`}
          >
            <div className="border-b border-default px-3 py-2">
              <div className="flex items-center gap-2">
                <UserIcon size={14} className="text-subtle" />
                <span className="text-sm font-medium text-primary">{me?.name}</span>
              </div>
              <div className="mt-0.5 text-xs text-subtle">@{me?.username}</div>
            </div>
            <div className="border-b border-default px-3 py-2">
              <div className="mb-1 text-xs font-medium uppercase tracking-wide text-subtle">Настройки</div>
              <div className="flex items-center justify-between py-1 text-sm text-subtle">
                <span>Язык интерфейса</span>
                <span title="Скоро — пока только русский">Русский</span>
              </div>
              <div className="flex items-center justify-between py-1 text-sm">
                <span className="text-secondary">Тема</span>
                <div className="flex overflow-hidden rounded border border-default">
                  {THEME_OPTIONS.map(({ value, label, Icon }) => (
                    <button
                      key={value}
                      onClick={() => handleSetTheme(value)}
                      title={label}
                      className={`flex h-6 w-6 items-center justify-center ${
                        theme === value ? "bg-accent text-on-accent" : "text-subtle hover:bg-muted-hover"
                      }`}
                    >
                      <Icon size={13} />
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <button
              onClick={() => {
                setShowSettings(true);
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 border-b border-default px-3 py-2 text-left text-sm text-secondary hover:bg-muted"
            >
              <Settings size={14} />
              Настройки ассистента
            </button>
            <button
              onClick={() => {
                window.dispatchEvent(new Event(OPEN_FEEDBACK_EVENT));
                setOpen(false);
              }}
              className="flex w-full items-center gap-2 border-b border-default px-3 py-2 text-left text-sm text-secondary hover:bg-muted"
            >
              <MessageSquare size={14} />
              Оставить отзыв
            </button>
            <button
              onClick={() => logout.mutate()}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-secondary hover:bg-muted"
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

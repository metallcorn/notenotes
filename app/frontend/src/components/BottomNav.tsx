import { Bell, FolderOpen, Home, Plus, Sparkles } from "lucide-react";
import { t } from "../i18n";

export type BottomNavTab = "home" | "notes" | "assistant" | "activity" | null;

// Нижняя плавающая панель разделов на телефоне (редизайн 21.10, макет
// «Главная»). На десктопе (lg:) те же разделы живут в левой колонке, и
// панель не нужна — скрыта классом, не условием: так разметка одна, и
// поворот планшета не перемонтирует её. Скрывается и в редакторе —
// там снизу живёт панель форматирования над клавиатурой.
//
// Рисуется как обычный футер колонки (shrink-0), а не fixed поверх
// контента: тогда ни одному списку не нужен «запас снизу», чтобы
// последняя строка не пряталась под панелью. Выглядит плавающей за счёт
// тёмной плашки на фоне приложения.
export default function BottomNav({
  active,
  activityBadge,
  onHome,
  onNotes,
  onCreate,
  onAssistant,
  onActivity,
}: {
  active: BottomNavTab;
  activityBadge: number;
  onHome: () => void;
  onNotes: () => void;
  onCreate: () => void;
  onAssistant: () => void;
  onActivity: () => void;
}) {
  const item = (tab: Exclude<BottomNavTab, null>, label: string, onClick: () => void, Icon: typeof Home) => (
    <button
      type="button"
      aria-label={label}
      aria-current={active === tab ? "page" : undefined}
      onClick={onClick}
      className={`relative flex h-16 items-center justify-center transition-colors ${
        active === tab ? "text-nav-text" : "text-nav-muted hover:text-nav-text"
      }`}
    >
      <Icon size={24} strokeWidth={2.2} />
      {tab === "activity" && activityBadge > 0 && (
        <span className="absolute right-[22px] top-4 h-[9px] w-[9px] rounded-full bg-lime" aria-hidden="true" />
      )}
    </button>
  );

  return (
    <nav aria-label="Разделы" className="shrink-0 bg-app px-4 pb-3 pt-2 lg:hidden">
      <div className="grid h-16 grid-cols-5 items-center rounded-3xl bg-nav shadow-nav">
        {item("home", t("nav.home"), onHome, Home)}
        {item("notes", t("nav.notes"), onNotes, FolderOpen)}
        <button
          type="button"
          aria-label={t("nav.create")}
          title={t("nav.create")}
          onClick={onCreate}
          className="flex h-16 items-center justify-center"
        >
          <span className="flex h-[52px] w-[52px] items-center justify-center rounded-2xl bg-lime text-on-lime transition-transform active:scale-95">
            <Plus size={26} strokeWidth={2.6} />
          </span>
        </button>
        {item("assistant", t("nav.assistant"), onAssistant, Sparkles)}
        {item("activity", t("nav.activity"), onActivity, Bell)}
      </div>
    </nav>
  );
}

import type { NodeViewProps } from "@tiptap/react";
import { NodeViewWrapper } from "@tiptap/react";
import { AlarmClock, AlertTriangle, Check } from "lucide-react";
import { useAllNotifications } from "../api/hooks";

// Реальная жалоба: голая иконка ⏰ без подписи ("не понимаю что я там
// написал") и без реакции на то, что напоминание уже сработало/выполнено
// ("что будет когда оно перестанет быть актуальным?"). Заголовок — из
// атрибута узла (сохранён в момент создания, не пропадёт даже если
// уведомление потом удалят). Статус — живой, сверяется со списком
// уведомлений при каждом рендере (useAllNotifications, тот же запрос, что
// уже кэширован для ActivityView.tsx) — те же три состояния и та же
// цветовая логика, что там: выполнено (resolved_at), просрочено
// (trigger_at прошёл, не выполнено), ждёт своего времени.
export default function ReminderAnchorCard({ node }: NodeViewProps) {
  const { notificationId, title } = node.attrs as { notificationId: string | null; title: string };
  const { data: notifications } = useAllNotifications();
  const notification = notifications?.find((n) => n.id === notificationId);

  const resolved = !!notification?.resolved_at;
  const overdue =
    !resolved && !!notification?.trigger_at && new Date(notification.trigger_at).getTime() <= Date.now();

  const Icon = resolved ? Check : overdue ? AlertTriangle : AlarmClock;
  const colorClass = resolved
    ? "border-green-300 bg-green-50 text-green-700"
    : overdue
      ? "border-amber-300 bg-amber-50 text-amber-700"
      : "border-slate-300 bg-slate-50 text-slate-600";

  const tooltip = notification
    ? resolved
      ? `Выполнено: ${title}`
      : notification.trigger_at
        ? `${overdue ? "Должно было сработать" : "Сработает"} ${new Date(notification.trigger_at).toLocaleString("ru-RU")}: ${title}`
        : title
    : title;

  return (
    // data-reminder-id ЯВНО на обёртке: в отличие от статичного renderHTML
    // (который ProseMirror сериализует сам), при addNodeView() DOM рисуем
    // мы сами через React — атрибуты из addAttributes().renderHTML() сюда
    // не подставляются автоматически. Без этого NoteEditor.tsx искал бы
    // элемент по data-reminder-id и никогда не находил (реальный баг,
    // пойманный до деплоя при переходе с renderHTML на NodeView).
    <NodeViewWrapper as="span" className="inline-block align-middle" data-reminder-id={notificationId} title={tooltip}>
      <span
        className={`inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-xs ${colorClass} ${resolved ? "line-through opacity-70" : ""}`}
      >
        <Icon size={11} />
        {title || "Напоминание"}
      </span>
    </NodeViewWrapper>
  );
}

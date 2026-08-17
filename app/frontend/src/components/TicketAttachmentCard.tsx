import { useEffect, useRef, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import QRCode from "qrcode";
import {
  AlarmClock,
  Armchair,
  Bus,
  Calendar,
  CalendarPlus,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
  MapPin,
  Plane,
  QrCode,
  RefreshCw,
  Ticket,
  Train,
  X,
} from "lucide-react";
import type { TicketAttachmentData } from "../extensions/TicketAttachment";
import { useCreateReminder, useReprocessUpload } from "../api/hooks";
import { ExpandedTextPanel } from "./RecognizedTextView";

const UPLOAD_ID_RE = /\/api\/uploads\/([0-9a-f-]{36})/i;

// Предустановленные смещения — не произвольный ввод времени: билет уже
// даёт единственную осмысленную точку отсчёта (время отправления), выбор
// сводится к "за сколько до", а не к вводу даты руками.
const REMINDER_PRESETS = [
  { label: "За 30 мин", hours: 0.5 },
  { label: "За 1 час", hours: 1 },
  { label: "За 2 часа", hours: 2 },
  { label: "За 1 день", hours: 24 },
];

const TICKET_ICONS: Record<string, typeof Ticket> = {
  train: Train,
  flight: Plane,
  bus: Bus,
  event: Ticket,
  other: Ticket,
};

const TICKET_LABELS: Record<string, string> = {
  train: "ЖД-билет",
  flight: "Авиабилет",
  bus: "Автобусный билет",
  event: "Билет на мероприятие",
  other: "Билет",
};

function formatDateTime(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

// Оригинал (картинка или PDF) — тот же паттерн полноэкранного оверлея, что
// PdfPreviewOverlay в DocumentAttachmentCard.tsx, но общий для обоих типов
// файла: билет чаще всего скриншот/фото, но иногда PDF-посадочный талон.
function TicketPreviewOverlay({ url, isPdf, onClose }: { url: string; isPdf: boolean; onClose: () => void }) {
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/80 p-2 sm:p-6">
      <button
        onClick={onClose}
        title="Закрыть (Esc)"
        className="mb-2 flex h-9 w-9 shrink-0 items-center justify-center self-end rounded-full bg-black/50 text-white hover:bg-black/70"
      >
        <X size={18} />
      </button>
      {isPdf ? (
        <iframe src={url} title={url} className="min-h-0 w-full flex-1 rounded bg-white" />
      ) : (
        <img src={url} alt="" className="m-auto max-h-full max-w-full rounded object-contain" />
      )}
    </div>
  );
}

// «Предъявить билет» — крупный QR на весь экран, чтобы сканер спокойно
// считал его с телефона. Код здесь ПЕРЕГЕНЕРИРУЕТСЯ на фронте из строки,
// декодированной бэкендом (app/tickets.py, pyzbar) — не картинка с
// бэкенда: ТЗ §7 запрещает хранить картинки как base64 в контенте
// заметки, а тут и не нужно — исходных данных QR достаточно, чтобы
// нарисовать его заново любого размера.
function TicketQrOverlay({
  code,
  title,
  datetimeStart,
  seat,
  onClose,
}: {
  code: string;
  title: string;
  datetimeStart: string;
  seat: string;
  onClose: () => void;
}) {
  const [dataUrl, setDataUrl] = useState<string | null>(null);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(code, { width: 800, margin: 1 })
      .then((url) => {
        if (!cancelled) setDataUrl(url);
      })
      .catch(() => {
        if (!cancelled) setDataUrl(null);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-white p-6">
      <button
        onClick={onClose}
        title="Закрыть (Esc)"
        className="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-full bg-slate-100 text-slate-500 hover:bg-slate-200"
      >
        <X size={18} />
      </button>
      {title && <div className="text-center text-lg font-medium text-slate-800">{title}</div>}
      {dataUrl ? (
        // Инлайн-стиль, не className: этот <img> — DOM-потомок .tiptap
        // (NodeView лежит внутри ProseMirror-дерева даже при
        // position:fixed — position меняет визуальное позиционирование,
        // не DOM-предков), а .tiptap img{max-width:100%} в index.css
        // специфичнее класса .max-w-sm (доп. элементный селектор) и
        // перебивал бы его через containing block фиксированного элемента
        // (весь viewport) — картинка раздувалась на весь экран.
        <img src={dataUrl} alt="QR-код билета" style={{ width: "100%", maxWidth: "24rem" }} />
      ) : (
        <div className="flex h-64 w-64 items-center justify-center text-sm text-slate-400">Генерация QR…</div>
      )}
      {(datetimeStart || seat) && (
        <div className="text-center text-sm text-slate-500">
          {datetimeStart && formatDateTime(datetimeStart)}
          {datetimeStart && seat && " · "}
          {seat}
        </div>
      )}
    </div>
  );
}

export default function TicketAttachmentCard({ node, editor, getPos }: NodeViewProps) {
  const {
    url,
    filename,
    ticketType,
    datetimeStart,
    datetimeEnd,
    locationFrom,
    locationTo,
    seat,
    title,
    rawText,
    code,
  } = node.attrs as TicketAttachmentData;
  const [expanded, setExpanded] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [qrOpen, setQrOpen] = useState(false);
  const [reminderMenuOpen, setReminderMenuOpen] = useState(false);
  const [reminderConfirm, setReminderConfirm] = useState<{ hours: number; triggerAt: Date } | null>(null);
  const [reminderDone, setReminderDone] = useState(false);
  const createReminder = useCreateReminder();
  const reprocess = useReprocessUpload();
  const cardRef = useRef<HTMLDivElement>(null);

  const isPdf = filename.toLowerCase().endsWith(".pdf");
  const Icon = TICKET_ICONS[ticketType] ?? Ticket;
  const label = TICKET_LABELS[ticketType] ?? TICKET_LABELS.other;
  const uploadId = url.match(UPLOAD_ID_RE)?.[1] ?? null;

  // Реальный найденный баг: у карточки билета не было способа попросить
  // распознать заново, в отличие от документов/картинок в заметке
  // (DocumentAttachmentCard.tsx) — а OCR вероятностный, реально ловили
  // случай, когда дата мероприятия крупным чётким текстом на самой
  // картинке, но vision-модель её не расшифровала. Билет всегда собран
  // из картинки (tickets.py запускается только из vision.py) — PDF сюда
  // не попадает, isPdf оставляем как есть на всякий случай.
  async function handleReprocess() {
    if (!uploadId || isPdf || typeof getPos !== "function") return;
    // Тот же плейсхолдер, что vision.py.placeholder_text() — именно его
    // ищет и заменяет tickets.py, когда распознавание закончится снова.
    const placeholder = `⏳ Описание изображения ${uploadId} обрабатывается…`;
    const pos = getPos();
    editor
      .chain()
      .focus()
      .deleteRange({ from: pos, to: pos + node.nodeSize })
      .insertContentAt(pos, { type: "paragraph", content: [{ type: "text", text: placeholder }] })
      .run();
    await reprocess.mutateAsync(uploadId);
  }

  const googleCalendarUrl = (() => {
    if (!datetimeStart) return null;
    const fmt = (iso: string) => iso.replace(/[-:]/g, "").replace(/\.\d+$/, "");
    const end = datetimeEnd || datetimeStart;
    const params = new URLSearchParams({ action: "TEMPLATE", text: title || label, dates: `${fmt(datetimeStart)}/${fmt(end)}` });
    if (locationFrom) params.set("location", locationFrom);
    return `https://calendar.google.com/calendar/render?${params.toString()}`;
  })();

  const icsUrl = (() => {
    if (!datetimeStart) return null;
    const params = new URLSearchParams({
      title: title || label,
      start: datetimeStart,
      end: datetimeEnd || datetimeStart,
      all_day: "false",
      location: locationFrom || "",
    });
    return `/api/calendar/event.ics?${params.toString()}`;
  })();

  // Само нажатие пресета — не создание: сначала показываем, на какое
  // ИМЕННО абсолютное время встанет напоминание, и ждём отдельного "Да"
  // (то же правило, что у create_reminder в диалоге с ассистентом — не
  // ставить напоминание молча по одному клику без явного подтверждения).
  function pickPreset(hours: number) {
    if (!datetimeStart) return;
    const triggerAt = new Date(new Date(datetimeStart).getTime() - hours * 3600_000);
    setReminderConfirm({ hours, triggerAt });
    setReminderMenuOpen(false);
  }

  function confirmReminder() {
    if (!reminderConfirm) return;
    // itemId — из storage расширения (см. TicketAttachment.ts), не пропа:
    // без него уведомление создавалось без привязки к билету и клик по
    // нему в центре уведомлений не открывал ничего (реальный найденный
    // баг — "почему уведомления никуда не ведут").
    const itemId = editor.storage.ticketAttachment?.itemId as string | null | undefined;
    createReminder.mutate(
      {
        title: `${label}: ${title || filename}`,
        body: locationFrom || locationTo ? `${locationFrom}${locationFrom && locationTo ? " → " : ""}${locationTo}` : "",
        trigger_at: reminderConfirm.triggerAt.toISOString(),
        ...(itemId ? { item_id: itemId } : {}),
      },
      { onSuccess: () => setReminderDone(true) },
    );
    setReminderConfirm(null);
  }

  return (
    // Реальный найденный баг (тот же, что чинили сегодня у карточки
    // документа/картинки — найден чтением исходников @tiptap/core): дело
    // не только в data-drag-handle — ГЛАВНОЕ, что сам HTML-атрибут
    // draggable=true на NodeViewWrapper браузер распознаёт независимо от
    // data-drag-handle (та проверка чисто внутри TipTap, уже ПОСЛЕ того,
    // как браузер решил, что это перетаскивание, а не выделение текста).
    // draggable теперь ТОЛЬКО на верхней кнопке — dragstart всплывает,
    // обработчик NodeViewWrapper всё равно сработает для неё.
    <NodeViewWrapper as="div" className="my-1">
      <div ref={cardRef} className="max-w-sm rounded border border-violet-200 bg-violet-50">
        <button
          data-drag-handle
          draggable
          onClick={() => setPreviewOpen(true)}
          className="flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-violet-100"
        >
          <Icon size={18} className="mt-0.5 shrink-0 text-violet-600" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-xs font-medium uppercase tracking-wide text-violet-600">{label}</div>
            <div className="truncate text-sm font-medium text-slate-800">{title || filename || "Билет"}</div>
          </div>
        </button>

        <div className="space-y-1 border-t border-violet-200 px-3 py-2 text-xs text-slate-700">
          {datetimeStart && (
            <div className="flex items-center gap-1.5">
              <Calendar size={12} className="shrink-0 text-slate-400" />
              {formatDateTime(datetimeStart)}
            </div>
          )}
          {(locationFrom || locationTo) && (
            <div className="flex items-center gap-1.5">
              <MapPin size={12} className="shrink-0 text-slate-400" />
              <span className="truncate">
                {locationFrom}
                {locationFrom && locationTo && " → "}
                {locationTo}
              </span>
            </div>
          )}
          {seat && (
            <div className="flex items-center gap-1.5">
              <Armchair size={12} className="shrink-0 text-slate-400" />
              {seat}
            </div>
          )}
        </div>

        {datetimeStart && (
          // onMouseDown/stopPropagation на всём ряду — реальный найденный
          // баг: карточка (NodeViewWrapper) сама draggable для
          // перетаскивания как блока, и без остановки события ProseMirror
          // успевал перехватить mousedown РАНЬШЕ клика по ссылке (тот же
          // класс бага, что уже чинили сегодня у кнопки ИИ в BubbleMenu) —
          // из-за этого клик по "Google Календарь" визуально выделял текст
          // соседних элементов и иногда срабатывал на обеих ссылках сразу
          // (открывались две вкладки).
          <div className="relative border-t border-violet-200 px-3 py-1.5" onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex flex-wrap items-center gap-1.5">
              <a
                href={googleCalendarUrl ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
                // style, не className — .tiptap a в index.css (цвет+подчёркивание
                // для обычных ссылок заметки) специфичнее text-slate-700 и
                // побеждал бы его (реальный найденный баг: кнопка синяя и
                // подчёркнутая вместо серой пилюли как у соседних кнопок).
                style={{ color: "inherit", textDecoration: "none" }}
                className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
              >
                <CalendarPlus size={12} /> Google Календарь
              </a>
              <a
                href={icsUrl ?? undefined}
                style={{ color: "inherit", textDecoration: "none" }}
                className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
              >
                <CalendarPlus size={12} /> .ics
              </a>
              {reminderDone ? (
                <span className="flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-1 text-xs text-green-700">
                  <Check size={12} /> Напоминание создано
                </span>
              ) : (
                <button
                  onClick={() => setReminderMenuOpen((v) => !v)}
                  className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-2.5 py-1 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
                >
                  <AlarmClock size={12} /> Напомнить
                </button>
              )}
            </div>

            {reminderMenuOpen && (
              <div className="absolute left-3 top-full z-10 mt-1 flex flex-col gap-0.5 rounded border bg-white p-1 shadow-lg">
                {REMINDER_PRESETS.map((preset) => (
                  <button
                    key={preset.hours}
                    onClick={() => pickPreset(preset.hours)}
                    className="whitespace-nowrap rounded px-2 py-1 text-left text-xs text-slate-700 hover:bg-slate-100"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            )}

            {reminderConfirm && (
              // Явное подтверждение абсолютного времени, не молчаливое
              // создание по одному клику пресета — тот же принцип, что у
              // create_reminder в диалоге с ассистентом (CLAUDE.md).
              <div className="mt-1.5 flex items-center justify-between gap-2 rounded border border-violet-300 bg-violet-50 px-2 py-1.5 text-xs">
                <span className="text-slate-700">Напомнить {formatDateTime(reminderConfirm.triggerAt.toISOString())}?</span>
                <div className="flex shrink-0 gap-1">
                  <button
                    onClick={confirmReminder}
                    disabled={createReminder.isPending}
                    className="rounded bg-slate-900 px-2 py-0.5 text-white hover:bg-slate-800 disabled:opacity-50"
                  >
                    Да
                  </button>
                  <button
                    onClick={() => setReminderConfirm(null)}
                    className="rounded border border-slate-300 px-2 py-0.5 text-slate-600 hover:bg-slate-100"
                  >
                    Отмена
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {code && (
          <button
            onClick={() => setQrOpen(true)}
            className="flex w-full items-center justify-center gap-1.5 border-t border-violet-200 bg-violet-600 py-2 text-sm font-medium text-white hover:bg-violet-700"
          >
            <QrCode size={14} />
            Предъявить билет
          </button>
        )}

        <div className="flex items-center border-t border-violet-200">
          <a
            href={url}
            download={filename || undefined}
            title="Скачать"
            style={{ color: "inherit", textDecoration: "none" }}
            className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700"
          >
            <Download size={13} />
          </a>
          {!isPdf && uploadId && (
            <button
              onClick={handleReprocess}
              disabled={reprocess.isPending}
              title="Распознать заново"
              className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700 disabled:opacity-50"
            >
              <RefreshCw size={13} className={reprocess.isPending ? "animate-spin" : ""} />
            </button>
          )}
          {rawText && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex flex-1 items-center gap-1 px-2 py-1.5 text-xs text-slate-500 hover:bg-violet-100"
            >
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {expanded ? "Скрыть распознанный текст" : "Показать распознанный текст"}
            </button>
          )}
        </div>
        {rawText && expanded && <ExpandedTextPanel anchorRef={cardRef} text={rawText} />}
      </div>
      {previewOpen && <TicketPreviewOverlay url={url} isPdf={isPdf} onClose={() => setPreviewOpen(false)} />}
      {qrOpen && code && (
        <TicketQrOverlay
          code={code}
          title={title}
          datetimeStart={datetimeStart}
          seat={seat}
          onClose={() => setQrOpen(false)}
        />
      )}
    </NodeViewWrapper>
  );
}

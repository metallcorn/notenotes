import { useEffect, useRef, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import QRCode from "qrcode";
import { attachmentTextId, useAttachmentText } from "../lib/attachmentText";
import {
  AlarmClock,
  Armchair,
  Bus,
  CalendarPlus,
  Check,
  ChevronDown,
  ChevronUp,
  Download,
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
import { dateLocale } from "../i18n";

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
  return d.toLocaleString(dateLocale, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
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
    <div className="modal-in fixed inset-0 z-50 flex flex-col bg-black/80 p-2 sm:p-6">
      <button
        onClick={onClose}
        title="Закрыть (Esc)"
        className="mb-2 flex h-9 w-9 shrink-0 items-center justify-center self-end rounded-full bg-black/50 text-white hover:bg-black/70"
      >
        <X size={18} />
      </button>
      {isPdf ? (
        <iframe src={url} title={url} className="min-h-0 w-full flex-1 rounded bg-surface" />
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
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-surface p-6">
      <button
        onClick={onClose}
        title="Закрыть (Esc)"
        className="absolute right-4 top-4 flex h-9 w-9 items-center justify-center rounded-full bg-muted-hover text-subtle hover:bg-muted-active"
      >
        <X size={18} />
      </button>
      {title && <div className="text-center text-lg font-medium text-primary">{title}</div>}
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
        <div className="flex h-64 w-64 items-center justify-center text-sm text-subtle">Генерация QR…</div>
      )}
      {(datetimeStart || seat) && (
        <div className="text-center text-sm text-subtle">
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
    rawText: inlineText,
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
  // Распознанный текст билета — из загрузки (lib/attachmentText.ts).
  const { text: rawText } = useAttachmentText(attachmentTextId(url), inlineText);

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
    <NodeViewWrapper as="div" className="my-2">
      {/* Макет «Заметка: чтение» (21.10): тёмная карточка билета — подпись и
          дата капителью, крупно откуда → куда со временем, лаймовая стрелка,
          действия чипами, «Предъявить билет» лаймовой кнопкой. */}
      <div ref={cardRef} className="w-full overflow-hidden rounded-3xl bg-nav p-4 text-nav-text shadow-nav md:max-w-lg">
        <button
          data-drag-handle
          draggable
          onClick={() => setPreviewOpen(true)}
          title="Открыть билет"
          className="flex w-full items-center justify-between gap-3 text-left"
        >
          <span className="flex min-w-0 items-center gap-1.5 text-xs font-extrabold uppercase tracking-wider text-nav-muted">
            <Icon size={14} className="shrink-0 text-lime" />
            <span className="truncate">{label}{title ? ` · ${title}` : ""}</span>
          </span>
          {datetimeStart && (
            <span className="shrink-0 text-xs font-extrabold uppercase tracking-wider text-nav-muted">
              {new Date(datetimeStart).toLocaleDateString(dateLocale, { day: "numeric", month: "short" }).replace(".", "")}
            </span>
          )}
        </button>

        {(locationFrom || locationTo || datetimeStart) && (
          <div className="mt-3 flex items-center justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="truncate text-[26px] font-extrabold leading-none tracking-tight">{locationFrom || "—"}</div>
              {datetimeStart && (
                <div className="mt-1 text-[13px] font-bold text-nav-muted">
                  {new Date(datetimeStart).toLocaleTimeString(dateLocale, { hour: "2-digit", minute: "2-digit" })}
                </div>
              )}
            </div>
            {locationTo && (
              <>
                <svg width="56" height="20" viewBox="0 0 64 20" fill="none" stroke="currentColor" strokeWidth="2" className="shrink-0 text-lime" aria-hidden="true">
                  <path d="M2 10h56M50 4l8 6-8 6" />
                </svg>
                <div className="min-w-0 flex-1 text-right">
                  <div className="truncate text-[26px] font-extrabold leading-none tracking-tight">{locationTo}</div>
                  {datetimeEnd && (
                    <div className="mt-1 text-[13px] font-bold text-nav-muted">
                      {new Date(datetimeEnd).toLocaleTimeString(dateLocale, { hour: "2-digit", minute: "2-digit" })}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        )}

        <div className="relative mt-3.5 flex flex-wrap items-center gap-1.5" onMouseDown={(e) => e.stopPropagation()}>
          {seat && (
            <span className="flex h-8 items-center gap-1 rounded-full bg-white/10 px-3 text-xs font-bold">
              <Armchair size={12} /> {seat}
            </span>
          )}
          {datetimeStart && (
            <>
              <a
                href={googleCalendarUrl ?? undefined}
                target="_blank"
                rel="noopener noreferrer"
                // style, не className — .tiptap a в index.css (цвет+подчёркивание
                // для обычных ссылок заметки) специфичнее и побеждал бы.
                style={{ color: "inherit", textDecoration: "none" }}
                className="flex h-8 items-center gap-1 rounded-full bg-white/10 px-3 text-xs font-bold hover:bg-white/20"
              >
                <CalendarPlus size={12} /> Google Календарь
              </a>
              <a
                href={icsUrl ?? undefined}
                style={{ color: "inherit", textDecoration: "none" }}
                className="flex h-8 items-center gap-1 rounded-full bg-white/10 px-3 text-xs font-bold hover:bg-white/20"
              >
                <CalendarPlus size={12} /> .ics
              </a>
              {reminderDone ? (
                <span className="flex h-8 items-center gap-1 rounded-full bg-lime px-3 text-xs font-extrabold text-on-lime">
                  <Check size={12} /> Напомню
                </span>
              ) : (
                <button
                  onClick={() => setReminderMenuOpen((v) => !v)}
                  className="flex h-8 items-center gap-1 rounded-full bg-white/10 px-3 text-xs font-bold hover:bg-white/20"
                >
                  <AlarmClock size={12} /> Напомнить
                </button>
              )}
            </>
          )}

          {reminderMenuOpen && (
            <div className="absolute left-0 top-full z-10 mt-1 flex flex-col gap-0.5 rounded-2xl border bg-surface p-1.5 text-primary shadow-lg">
              {REMINDER_PRESETS.map((preset) => (
                <button
                  key={preset.hours}
                  onClick={() => pickPreset(preset.hours)}
                  className="min-h-9 whitespace-nowrap rounded-xl px-3 text-left text-sm font-semibold text-secondary hover:bg-muted"
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
            <div className="mt-1 flex w-full items-center justify-between gap-2 rounded-2xl bg-white/10 px-3 py-2 text-xs font-bold">
              <span>Напомнить {formatDateTime(reminderConfirm.triggerAt.toISOString())}?</span>
              <div className="flex shrink-0 gap-1">
                <button
                  onClick={confirmReminder}
                  disabled={createReminder.isPending}
                  className="h-8 rounded-full bg-lime px-3 font-extrabold text-on-lime disabled:opacity-50"
                >
                  Да
                </button>
                <button onClick={() => setReminderConfirm(null)} className="h-8 rounded-full bg-white/10 px-3 font-bold">
                  Отмена
                </button>
              </div>
            </div>
          )}
        </div>

        {code && (
          <button
            onClick={() => setQrOpen(true)}
            className="mt-3.5 flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-lime text-[15px] font-extrabold text-on-lime hover:bg-lime/90"
          >
            <QrCode size={16} />
            Предъявить билет
          </button>
        )}

        <div className="-mx-1 mt-2 flex items-center text-nav-muted">
          <a
            href={url}
            download={filename || undefined}
            title="Скачать"
            style={{ color: "inherit", textDecoration: "none" }}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl hover:bg-white/10 hover:text-nav-text"
          >
            <Download size={14} />
          </a>
          {!isPdf && uploadId && (
            <button
              onClick={handleReprocess}
              disabled={reprocess.isPending}
              title="Распознать заново"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl hover:bg-white/10 hover:text-nav-text disabled:opacity-50"
            >
              <RefreshCw size={14} className={reprocess.isPending ? "animate-spin" : ""} />
            </button>
          )}
          {rawText && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex h-9 flex-1 items-center gap-1 rounded-xl px-2 text-xs font-bold hover:bg-white/10 hover:text-nav-text"
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

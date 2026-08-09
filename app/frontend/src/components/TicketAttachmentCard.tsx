import { useEffect, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import QRCode from "qrcode";
import {
  Armchair,
  Bus,
  Calendar,
  ChevronDown,
  ChevronUp,
  Download,
  MapPin,
  Plane,
  QrCode,
  Ticket,
  Train,
  X,
} from "lucide-react";
import type { TicketAttachmentData } from "../extensions/TicketAttachment";

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

export default function TicketAttachmentCard({ node }: NodeViewProps) {
  const {
    url,
    filename,
    ticketType,
    datetimeStart,
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

  const isPdf = filename.toLowerCase().endsWith(".pdf");
  const Icon = TICKET_ICONS[ticketType] ?? Ticket;
  const label = TICKET_LABELS[ticketType] ?? TICKET_LABELS.other;

  return (
    <NodeViewWrapper as="div" className="my-1" data-drag-handle draggable>
      <div className="max-w-sm rounded border border-violet-200 bg-violet-50">
        <button
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
            className="flex h-8 w-8 shrink-0 items-center justify-center text-slate-400 hover:text-slate-700"
          >
            <Download size={13} />
          </a>
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
        {rawText && expanded && (
          // contentEditable=true — та же обёртка-остров, что в
          // DocumentAttachmentCard.tsx: узел atom, а браузеры обращаются с
          // contenteditable=false внутри редактируемой заметки как с одним
          // неделимым блоком выделения без этого (реальная жалоба, уже
          // ловили на карточке документа).
          <div
            data-doc-text
            contentEditable
            suppressContentEditableWarning
            draggable={false}
            onKeyDown={(e) => e.preventDefault()}
            onPaste={(e) => e.preventDefault()}
            onBeforeInput={(e) => e.preventDefault()}
            onDragStart={(e) => e.preventDefault()}
            className="max-h-96 cursor-text select-text overflow-y-auto whitespace-pre-wrap border-t border-violet-200 px-3 py-2 text-xs text-slate-700 outline-none"
          >
            {rawText}
          </div>
        )}
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

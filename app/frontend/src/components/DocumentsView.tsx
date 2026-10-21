import { useMemo, useState } from "react";
import { AlertTriangle, ChevronLeft, Clock, FileText, Folder, Layers, Search } from "lucide-react";

import { useDocuments } from "../api/hooks";
import type { DocumentEntry, DocumentSeries } from "../api/types";
import { ListSkeleton } from "./Skeleton";
import { t } from "../i18n";

// Сквозной вид «Документы». Запрос владельца: «возможно отсортировать или
// пересобрать отдельно где-то все документы, потому что всё сейчас так
// раскидано».
//
// ЭТО ВИД, А НЕ ПЕРЕМЕЩЕНИЕ. Автосортировку по папкам владелец забраковал
// сам («слишком много неоднозначности»), и это верно: часть спейсов
// расшарена с женой, так что неверный переезд документа — не
// «неаккуратно», а чужой доступ. Здесь ничего не двигается, доступы не
// меняются; это те же данные, собранные по-другому.
//
// Серии наверху, потому что в них и живёт польза: месячный пакет от
// бухгалтера виден линией, и сразу понятно, пришёл ли очередной.

const STATUS_STYLE: Record<string, { label: string; className: string; Icon: typeof Clock }> = {
  "задерживается": { label: "задерживается", className: "bg-danger/10 text-danger", Icon: AlertTriangle },
  "ожидается": { label: "ожидается", className: "bg-warning/15 text-warning", Icon: Clock },
  "ок": { label: "по графику", className: "bg-muted-active text-subtle", Icon: Clock },
};

function formatSize(bytes: number | null): string {
  if (!bytes) return "";
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}

function SeriesCard({ series }: { series: DocumentSeries }) {
  const style = STATUS_STYLE[series.status] ?? STATUS_STYLE["ок"];
  return (
    <div className="row-fade-in border-b px-4 py-3">
      <div className="flex items-center gap-2">
        <Layers size={14} className="shrink-0 text-subtle" />
        <div className="min-w-0 flex-1 truncate text-sm font-medium text-primary">{series.title}</div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${style.className}`}>
          {style.label}
        </span>
      </div>

      <div className="mt-2 flex flex-wrap gap-1">
        {series.instalments.map((i) => (
          <a
            key={i.upload_id}
            href={`/api/uploads/${i.upload_id}`}
            target="_blank"
            rel="noreferrer"
            title={`${i.filename} — ${i.space_name}, получено ${i.received_on}`}
            className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-secondary hover:bg-muted-hover"
          >
            {i.period}
          </a>
        ))}
        {/* Пропуски — ровно то, чего не видно, пока файлы лежат по
            отдельности. Показываем только внутри наблюдаемого диапазона:
            что было до того, как человек начал складывать документы сюда,
            нас не касается. */}
        {series.gaps.map((g) => (
          <span key={g} className="rounded bg-danger/10 px-1.5 py-0.5 text-[11px] text-danger" title="нет в базе">
            {g} — нет
          </span>
        ))}
      </div>

      {series.expected_next && (
        <div className="mt-1.5 text-[11px] text-subtle">
          Следующий — {series.expected_next}
          {series.expected_by ? `, обычно приходит к ${series.expected_by}` : ""}
        </div>
      )}
    </div>
  );
}

function DocumentRow({ doc, onOpenItem }: { doc: DocumentEntry; onOpenItem: (spaceId: string, itemId: string) => void }) {
  return (
    <div className="row-fade-in flex items-center gap-2.5 border-b px-4 py-2.5">
      <FileText size={15} className="shrink-0 text-subtle" />
      <div className="min-w-0 flex-1">
        <a
          href={`/api/uploads/${doc.id}`}
          target="_blank"
          rel="noreferrer"
          className="block truncate text-sm text-primary hover:underline"
        >
          {doc.filename}
        </a>
        <div className="flex items-center gap-1.5 truncate text-xs text-subtle">
          <Folder size={10} className="shrink-0" />
          {doc.space_name}
          {doc.item_title && (
            <>
              <span>·</span>
              {/* Из списка можно попасть к документу В КОНТЕКСТ, а не
                  только скачать байты. */}
              <button
                onClick={() => doc.item_id && onOpenItem(doc.space_id, doc.item_id)}
                className="truncate hover:underline"
              >
                {doc.item_title}
              </button>
            </>
          )}
          <span>·</span>
          {doc.created_at}
          {doc.size_bytes ? (
            <>
              <span>·</span>
              {formatSize(doc.size_bytes)}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export default function DocumentsView({
  onBack,
  onOpenItem,
}: {
  onBack: () => void;
  onOpenItem: (spaceId: string, itemId: string) => void;
}) {
  const { data, isLoading } = useDocuments();
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return data?.documents ?? [];
    return (data?.documents ?? []).filter(
      (d) =>
        d.filename.toLowerCase().includes(needle) ||
        d.space_name.toLowerCase().includes(needle) ||
        (d.item_title ?? "").toLowerCase().includes(needle),
    );
  }, [data, query]);

  const series = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return data?.series ?? [];
    return (data?.series ?? []).filter((s) => s.title.toLowerCase().includes(needle));
  }, [data, query]);

  return (
    <div className="flex h-full w-full flex-col">
      <div className="flex items-center gap-3 p-3 pb-1">
        <button
          onClick={onBack}
          aria-label="Назад"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card lg:hidden"
        >
          <ChevronLeft size={20} strokeWidth={2.4} />
        </button>
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-extrabold tracking-tight text-primary lg:text-lg">{t("nav.documents")}</h1>
          {data && (
            <div className="text-xs font-semibold text-subtle">
              {data.documents.length} файлов, {data.series.length} серий
            </div>
          )}
        </div>
      </div>

      <label className="mx-3 mb-2 mt-2 flex h-12 items-center gap-2.5 rounded-2xl bg-surface pl-4 pr-3 shadow-float focus-within:ring-2 focus-within:ring-brand/40">
        <Search size={18} className="shrink-0 text-subtle" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Название, спейс или заметка"
          className="min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-subtle"
        />
      </label>

      <div className="flex-1 overflow-y-auto">
        {isLoading && <ListSkeleton rows={8} />}

        {!isLoading && series.length > 0 && (
          <>
            <div className="px-4 pb-1 pt-2 text-[11px] font-extrabold uppercase tracking-wider text-subtle">
              Серии
            </div>
            {series.map((s) => (
              <SeriesCard key={s.key} series={s} />
            ))}
          </>
        )}

        {!isLoading && (
          <>
            <div className="px-4 pb-1 pt-2 text-[11px] font-extrabold uppercase tracking-wider text-subtle">
              Все документы
            </div>
            {filtered.length === 0 ? (
              <div className="p-4 text-sm text-subtle">
                {query ? "Ничего не нашлось" : "Документов пока нет"}
              </div>
            ) : (
              filtered.map((d) => <DocumentRow key={d.id} doc={d} onOpenItem={onOpenItem} />)
            )}
          </>
        )}
      </div>
    </div>
  );
}

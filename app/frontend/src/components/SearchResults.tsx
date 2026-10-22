import { useSearch } from "../api/hooks";
import SemanticResults from "./SemanticResults";
import Spinner from "./Spinner";
import { t } from "../i18n";

const KIND_LABEL: Record<string, string> = { note: "заметка", list: "список", table: "таблица", dialog: "диалог" };

// Подсветка найденного слова в превью (макет «Поиск», 21.10).
function highlight(text: string, query: string) {
  const q = query.trim();
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return text;
  return (
    <>
      {text.slice(0, i)}
      <mark className="rounded bg-lime/70 px-0.5 text-primary">{text.slice(i, i + q.length)}</mark>
      {text.slice(i + q.length)}
    </>
  );
}

export default function SearchResults({
  query,
  selectedId,
  onSelect,
}: {
  query: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const { data: items, isLoading } = useSearch(query);

  const fast = items ?? [];

  return (
    <>
    <ul className="px-3 pt-2">
      {!isLoading && fast.length > 0 && (
        <li className="px-1 pb-1.5 text-[11px] font-extrabold uppercase tracking-wider text-subtle">{t("search.exact")}</li>
      )}
      {isLoading && (
        <li className="flex items-center gap-2 p-3 text-sm font-semibold text-subtle">
          <Spinner /> Ищем…
        </li>
      )}
      {!isLoading && fast.length === 0 && (
        // Показываем, только когда быстрый поиск отработал. Смысловой блок
        // ниже может ещё догружаться и что-то найти — «Ничего не найдено»
        // над ним выглядело бы прямым враньём.
        <li className="p-3 text-sm font-semibold text-subtle">Точных совпадений нет</li>
      )}
      {fast.map((item) => (
        <li key={item.id} className="pb-2">
          <button
            onClick={() => onSelect(item.id)}
            className={`block w-full rounded-2xl bg-surface p-3.5 text-left shadow-card ${
              selectedId === item.id ? "ring-2 ring-brand" : "hover:shadow-float"
            }`}
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-[15px] font-extrabold text-primary">
                {item.icon ? `${item.icon} ` : ""}
                {item.title || "Без названия"}
              </span>
              <span className="shrink-0 text-xs font-bold text-subtle">{KIND_LABEL[item.material_type] ?? ""}</span>
            </div>
            <div className="mt-0.5 line-clamp-2 text-[13px] leading-snug text-secondary">
              {highlight(item.content.slice(0, 160).replace(/\n/g, " "), query)}
            </div>
          </button>
        </li>
      ))}
    </ul>
    {/* Вторая, медленная половина того же потока (ТЗ §10): быстрые
        результаты выше уже на экране, смысловые подгружаются следом.
        Внутри SearchResults, а не рядом в AppShell — по ТЗ это ОДИН поток
        с прогрессивной загрузкой, и разносить его по двум местам значило
        бы приглашать к рассинхрону. */}
    <SemanticResults
      query={query}
      selectedId={selectedId}
      onSelect={onSelect}
      excludeIds={fast.map((i) => i.id)}
    />
    </>
  );
}

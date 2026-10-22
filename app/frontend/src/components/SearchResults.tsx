import { useSearch } from "../api/hooks";
import SemanticResults from "./SemanticResults";
import Spinner from "./Spinner";

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
            <div className="truncate text-[15px] font-extrabold text-primary">{item.title || "Без названия"}</div>
            <div className="mt-0.5 truncate text-[13px] text-subtle">
              {item.content.slice(0, 120).replace(/\n/g, " ")}
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

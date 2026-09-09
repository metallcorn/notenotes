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
    <ul>
      {isLoading && (
        <li className="flex items-center gap-2 p-3 text-sm text-subtle">
          <Spinner /> Ищем…
        </li>
      )}
      {!isLoading && fast.length === 0 && (
        // Показываем, только когда быстрый поиск отработал. Смысловой блок
        // ниже может ещё догружаться и что-то найти — «Ничего не найдено»
        // над ним выглядело бы прямым враньём.
        <li className="p-3 text-sm text-subtle">Точных совпадений нет</li>
      )}
      {fast.map((item) => (
        <li key={item.id}>
          <button
            onClick={() => onSelect(item.id)}
            className={`block w-full border-b px-3 py-2 text-left ${
              selectedId === item.id ? "bg-muted-hover" : "hover:bg-muted-hover"
            }`}
          >
            <div className="truncate text-sm font-medium text-primary">{item.title || "Без названия"}</div>
            <div className="mt-0.5 truncate text-xs text-subtle">
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

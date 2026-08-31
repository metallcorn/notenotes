import { useSearch } from "../api/hooks";
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

  return (
    <ul>
      {isLoading && (
        <li className="flex items-center gap-2 p-3 text-sm text-subtle">
          <Spinner /> Ищем…
        </li>
      )}
      {!isLoading && (items ?? []).length === 0 && <li className="p-3 text-sm text-subtle">Ничего не найдено</li>}
      {(items ?? []).map((item) => (
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
  );
}

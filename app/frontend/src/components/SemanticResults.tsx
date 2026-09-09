import { Sparkles } from "lucide-react";
import { useSemanticSearch } from "../api/hooks";
import Spinner from "./Spinner";

/**
 * Блок «Похожие по смыслу» — вторая, медленная половина поиска (ТЗ §10).
 *
 * По ТЗ это ОДИН поток с прогрессивной загрузкой, а не два режима:
 * пользователь печатает один раз и не выбирает, каким поиском искать.
 * Быстрые результаты (полнотекст) появляются мгновенно, этот блок
 * подгружается следом.
 *
 * Отдельным блоком под чертой, а не подмешиванием в общий список:
 * смысловые совпадения принципиально менее надёжны (порог измерен, см.
 * routers/search.py — диапазоны осмысленных и посторонних запросов
 * ПЕРЕКРЫВАЮТСЯ). Смешать их с точными — значит подорвать доверие и к
 * точным тоже.
 */
export default function SemanticResults({
  query,
  selectedId,
  onSelect,
  /** id из быстрой выдачи — их здесь не повторяем. */
  excludeIds,
}: {
  query: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
  excludeIds: string[];
}) {
  const { data, isLoading, isError } = useSemanticSearch(query);

  // Дубли из быстрой выдачи убираем: одна и та же заметка в двух блоках
  // подряд выглядит как ошибка, а не как «нашлось дважды».
  const hits = (data ?? []).filter((h) => !excludeIds.includes(h.item.id));

  // Пусто — блока нет вовсе. Заголовок «Похожие по смыслу» над пустотой
  // читался бы как поломка; лучше молча ничего, тем более что порог
  // намеренно строгий и пустой ответ здесь — нормальный исход.
  if (!isLoading && (isError || hits.length === 0)) return null;

  return (
    <div className="border-t">
      <div className="flex items-center gap-1.5 px-3 pb-1 pt-2 text-xs font-medium text-subtle">
        <Sparkles size={13} aria-hidden />
        Похожие по смыслу
        {/* Индикатор рядом с заголовком, а не вместо содержимого: блок
            обязан заявить о себе сразу, иначе кажется, что ничего не
            нашлось, и человек уходит раньше времени. */}
        {isLoading && <Spinner />}
      </div>
      <ul>
        {hits.map((hit) => (
          <li key={hit.item.id}>
            <button
              onClick={() => onSelect(hit.item.id)}
              className={`block w-full border-b px-3 py-2 text-left ${
                selectedId === hit.item.id ? "bg-muted-hover" : "hover:bg-muted-hover"
              }`}
            >
              <div className="truncate text-sm font-medium text-primary">
                {hit.item.title || "Без названия"}
              </div>
              {/* Совпавший КУСОК, а не начало заметки: без него результат по
                  документу на 80 тысяч знаков бесполезен — непонятно, что
                  в нём нашлось. Две строки, дальше многоточие. */}
              <div className="mt-0.5 line-clamp-2 text-xs text-subtle">
                {hit.excerpt.replace(/\s+/g, " ").trim()}
              </div>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

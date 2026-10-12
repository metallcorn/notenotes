// Скелетная подгрузка вместо одинокого спиннера.
//
// Реальная жалоба владельца 12.10: «подгрузки списков заметок не
// скелетные, а просто родинокий спинер». Разница не косметическая: спиннер
// по центру пустого экрана не говорит, ЧТО грузится и сколько этого будет,
// поэтому каждое открытие списка выглядит как «приложение задумалось».
// Скелет занимает ту же площадь и форму, что и будущие строки, — экран не
// прыгает в момент подстановки данных, и ожидание читается как «сейчас
// появится список», а не «что-то происходит».
//
// Почему своё, а не библиотека: это десяток строк CSS, а любая зависимость
// на 4 ГБ VPS ещё и попадает в бандл.

/** Один серый блок. Пульсация — в CSS (.skeleton), с учётом prefers-reduced-motion. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton rounded ${className}`} aria-hidden="true" />;
}

/**
 * Строки списка: иконка, заголовок, подпись. Повторяет геометрию
 * NoteList/DialogList/ActivityView, чтобы подстановка данных не дёргала
 * раскладку.
 *
 * Ширины заголовков намеренно РАЗНЫЕ и заданы массивом, а не случайным
 * числом: со Math.random() каждый ре-рендер менял бы ширину, и скелет
 * «мерцал» бы вместо спокойного ожидания.
 */
const TITLE_WIDTHS = ["w-3/4", "w-1/2", "w-2/3", "w-5/6", "w-2/5", "w-3/5"];

export function ListSkeleton({ rows = 5, withIcon = true }: { rows?: number; withIcon?: boolean }) {
  return (
    <div
      // role=status + aria-busy: для читалки это «идёт загрузка», а не
      // набор пустых блоков.
      role="status"
      aria-busy="true"
      aria-label="Загрузка списка"
      className="divide-y"
    >
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-start gap-2 px-4 py-3">
          {withIcon && <Skeleton className="mt-0.5 h-4 w-4 shrink-0" />}
          <div className="min-w-0 flex-1">
            <Skeleton className={`h-3.5 ${TITLE_WIDTHS[i % TITLE_WIDTHS.length]}`} />
            <Skeleton className="mt-2 h-2.5 w-1/4" />
          </div>
        </div>
      ))}
    </div>
  );
}

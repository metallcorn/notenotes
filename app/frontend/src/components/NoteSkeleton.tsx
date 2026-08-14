// Реальная жалоба: заметка появляется не мгновенно (запрос всё-таки
// летит на сервер), а до этого был просто спиннер по центру — заметный
// "скачок" макета, когда контент наконец прилетает. Силуэт, грубо
// повторяющий форму реальной заметки (шапка/тулбар/строки текста),
// ощущается быстрее и без скачка. animate-pulse — встроенная утилита
// Tailwind, свой keyframe не нужен.
export default function NoteSkeleton() {
  return (
    <div className="flex h-full flex-col overflow-hidden" aria-hidden="true">
      <div className="flex flex-col border-b">
        <div className="flex items-center gap-2 px-3 py-2">
          <div className="h-8 w-8 shrink-0 animate-pulse rounded bg-slate-200 lg:hidden" />
          <div className="h-6 w-2/5 animate-pulse rounded bg-slate-200" />
          <div className="ml-auto flex shrink-0 gap-2">
            <div className="h-7 w-7 animate-pulse rounded bg-slate-200" />
            <div className="h-7 w-7 animate-pulse rounded bg-slate-200" />
            <div className="h-7 w-7 animate-pulse rounded bg-slate-200" />
          </div>
        </div>
        <div className="flex gap-1 border-t px-2 py-1.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-7 w-7 shrink-0 animate-pulse rounded bg-slate-100" />
          ))}
        </div>
      </div>
      <div className="mx-auto w-full max-w-3xl flex-1 space-y-3 px-4 py-6">
        <div className="h-4 w-4/5 animate-pulse rounded bg-slate-200" />
        <div className="h-4 w-full animate-pulse rounded bg-slate-200" />
        <div className="h-4 w-11/12 animate-pulse rounded bg-slate-200" />
        <div className="h-4 w-3/5 animate-pulse rounded bg-slate-200" />
        <div className="h-4 w-full animate-pulse rounded bg-slate-200" />
        <div className="h-4 w-2/3 animate-pulse rounded bg-slate-200" />
      </div>
    </div>
  );
}

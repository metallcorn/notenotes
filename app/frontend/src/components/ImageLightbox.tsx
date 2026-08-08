import { useEffect, useRef, useState } from "react";
import type { TouchEvent as ReactTouchEvent } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

// Минимальная длина горизонтального свайпа, чтобы засчитать смену
// картинки — короче него слишком легко спутать с обычным тапом/дрожью
// пальца. Вертикаль отсекается отдельно (см. handleTouchEnd) — иначе
// вертикальный скролл/жест масштабирования тоже листал бы картинки.
const SWIPE_THRESHOLD_PX = 50;

// Полноэкранный просмотр картинки — общий для картинок внутри заметок
// (кнопка «Открыть» в ImageToolbar) и для картинок, которые показывает
// ассистент в чате (AssistantChat, включая галерею из нескольких картинок
// в одном ответе). Отдельного pinch-zoom не пишем: у viewport в index.html
// нет user-scalable=no/maximum-scale, так что браузер сам даёт жест
// масштабирования поверх fixed-оверлея — но листание свайпом браузер
// сам не умеет, это уже наш код (телефон — больше половины использования,
// одних кнопок ‹ › недостаточно).
export default function ImageLightbox({
  images,
  startIndex = 0,
  onClose,
}: {
  images: { src: string; alt?: string }[];
  startIndex?: number;
  onClose: () => void;
}) {
  const [index, setIndex] = useState(startIndex);
  const multiple = images.length > 1;
  const touchStartRef = useRef<{ x: number; y: number } | null>(null);

  function prev() {
    setIndex((i) => (i - 1 + images.length) % images.length);
  }
  function next() {
    setIndex((i) => (i + 1) % images.length);
  }

  function handleTouchStart(e: ReactTouchEvent) {
    // Больше одного касания — это pinch-zoom, не свайп-навигация; не
    // вмешиваемся, пусть браузер обрабатывает жест масштабирования сам.
    if (e.touches.length !== 1) {
      touchStartRef.current = null;
      return;
    }
    touchStartRef.current = { x: e.touches[0].clientX, y: e.touches[0].clientY };
  }

  function handleTouchEnd(e: ReactTouchEvent) {
    const start = touchStartRef.current;
    touchStartRef.current = null;
    if (!start || !multiple) return;
    const touch = e.changedTouches[0];
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    // Жест должен быть преимущественно горизонтальным — иначе обычный
    // вертикальный скролл/лёгкое дрожание пальца засчитывался бы за
    // пролистывание.
    if (Math.abs(dx) < SWIPE_THRESHOLD_PX || Math.abs(dx) < Math.abs(dy)) return;
    if (dx < 0) next();
    else prev();
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      else if (multiple && e.key === "ArrowLeft") prev();
      else if (multiple && e.key === "ArrowRight") next();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [multiple, images.length]);

  const current = images[index];
  if (!current) return null;

  return (
    <div
      onClick={onClose}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
    >
      <img src={current.src} alt={current.alt ?? ""} className="max-h-full max-w-full object-contain" />
      {multiple && (
        <>
          <button
            onClick={(e) => {
              e.stopPropagation();
              prev();
            }}
            title="Предыдущая картинка"
            className="fixed left-2 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70"
          >
            <ChevronLeft size={22} />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              next();
            }}
            title="Следующая картинка"
            className="fixed right-2 top-1/2 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full bg-black/50 text-white hover:bg-black/70"
          >
            <ChevronRight size={22} />
          </button>
          <div className="fixed bottom-4 left-1/2 -translate-x-1/2 rounded-full bg-black/50 px-3 py-1 text-xs text-white">
            {index + 1} / {images.length}
          </div>
        </>
      )}
    </div>
  );
}

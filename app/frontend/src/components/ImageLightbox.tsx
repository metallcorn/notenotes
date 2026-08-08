// Полноэкранный просмотр картинки — общий для картинок внутри заметок
// (кнопка «Открыть» в ImageToolbar) и для картинок, которые показывает
// ассистент в чате (AssistantChat). Отдельного pinch-zoom не пишем: у
// viewport в index.html нет user-scalable=no/maximum-scale, так что
// браузер сам даёт жест масштабирования поверх fixed-оверлея.
export default function ImageLightbox({
  src,
  alt,
  onClose,
}: {
  src: string;
  alt?: string;
  onClose: () => void;
}) {
  return (
    <div onClick={onClose} className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4">
      <img src={src} alt={alt ?? ""} className="max-h-full max-w-full object-contain" />
    </div>
  );
}

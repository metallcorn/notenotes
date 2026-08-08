// Сетка миниатюр для нескольких картинок в одном ответе ассистента
// (Telegram-style альбом, но без точного алгоритма адаптивной раскладки
// под пропорции каждого фото — избыточная сложность для чат-пузыря).
// Квадратные превью через object-cover аккуратно заполняют пространство
// при любом количестве картинок, чётном и нечётном.
export default function ImageGallery({
  images,
  onOpen,
}: {
  images: { src: string; alt?: string }[];
  onOpen: (index: number) => void;
}) {
  return (
    <div className={`my-1 grid gap-1 ${images.length <= 2 ? "grid-cols-2" : "grid-cols-3"}`}>
      {images.map((img, i) => (
        <button
          key={i}
          onClick={() => onOpen(i)}
          className="aspect-square overflow-hidden rounded border border-slate-200"
        >
          <img src={img.src} alt={img.alt ?? ""} loading="lazy" className="h-full w-full object-cover" />
        </button>
      ))}
    </div>
  );
}

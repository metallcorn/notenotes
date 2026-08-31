import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { Globe } from "lucide-react";
import { useLinkPreview } from "../api/hooks";
import { detectEmbed } from "../lib/embedPlatforms";
import VideoEmbedCard from "./VideoEmbedCard";

// Богатая карточка — linkPreview всегда блочный atom-узел
// (extensions/LinkPreview.ts, group: "block"), у него физически не бывает
// текста слева/справа на той же строке — только соседние абзацы
// сверху/снизу, которые к самой карточке отношения не имеют. Картинка/
// описание поэтому видны сразу, без наведения — не нужно наводить курсор
// на каждую ссылку в списке по очереди, чтобы понять, что там.
function RichCard({ url, favicon, title, imageUrl, description }: {
  url: string; favicon: string | null; title: string; imageUrl: string | null; description: string;
}) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="flex max-w-md overflow-hidden rounded border bg-slate-50 text-sm text-slate-800 no-underline hover:bg-slate-100"
    >
      {imageUrl && <img src={imageUrl} alt="" className="h-24 w-24 shrink-0 object-cover" />}
      <div className="min-w-0 flex-1 p-2">
        <div className="mb-1 flex items-center gap-1.5">
          {favicon ? (
            <img
              src={favicon}
              alt=""
              className="h-3.5 w-3.5 shrink-0"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            <Globe size={12} className="shrink-0 text-slate-400" />
          )}
          <span className="truncate font-medium">{title}</span>
        </div>
        {description && <div className="line-clamp-2 text-xs text-slate-600">{description}</div>}
      </div>
    </a>
  );
}

export default function LinkPreviewCard({ node }: NodeViewProps) {
  const url = node.attrs.url as string;
  const embed = detectEmbed(url);
  const { data, isLoading } = useLinkPreview(url, !!embed);

  // Известная видеоплатформа — сразу плеер, без похода за og:*
  // метаданными (реальная просьба пользователя после вставки ссылки на
  // YouTube).
  if (embed) {
    return <VideoEmbedCard url={url} embed={embed} />;
  }

  // Пока грузится — обычная синяя ссылка, не заглушка/скелетон (момент
  // короткий, мигать скелетоном ради него не стоит).
  if (isLoading || !data) {
    return (
      <NodeViewWrapper as="div" className="my-1">
        <a href={url} target="_blank" rel="noopener noreferrer" className="text-blue-600 underline">
          {url}
        </a>
      </NodeViewWrapper>
    );
  }

  // Реальная жалоба: карточку не удалось собрать (сайт требует
  // авторизацию, не ответил, заблокирован SSRF-проверкой и т.п.) —
  // рендерилась ТАКАЯ ЖЕ обычная синяя ссылка, как и в момент загрузки,
  // визуально неотличимая от "вставка вообще не сработала". На деле узел
  // создался и запрос ушёл, просто превью не собралось — маленькая иконка
  // с подсказкой явно показывает разницу.
  if (data.fetch_failed || !data.title) {
    return (
      <NodeViewWrapper as="div" className="my-1">
        <a
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          title="Не удалось загрузить превью — сайт не ответил или требует авторизацию"
          className="inline-flex items-center gap-1 text-blue-600 underline decoration-dotted"
        >
          <Globe size={12} className="shrink-0 text-slate-400" />
          {url}
        </a>
      </NodeViewWrapper>
    );
  }

  return (
    // Тот же баг, что нашли и починили в DeliveryWidgetCard.tsx: draggable
    // на обёртке, содержащей ссылку (тут — вся RichCard целиком является
    // <a target=_blank>), заставлял клик иногда открывать две вкладки
    // сразу (конфликт нативного "перетащить ссылку" браузера и обычной
    // навигации по клику). Узкий drag-handle без ссылки внутри сделать
    // некуда — вся ценность превью именно в кликабельности целиком.
    <NodeViewWrapper as="div" className="my-1">
      <RichCard
        url={url}
        favicon={data.favicon_url}
        title={data.title}
        imageUrl={data.image_url}
        description={data.description || ""}
      />
    </NodeViewWrapper>
  );
}

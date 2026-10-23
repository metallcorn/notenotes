import { useEffect, useRef, useState, type CSSProperties } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import Spinner from "./Spinner";
import { nodeAfter, useEditorTick } from "../lib/nodeSiblings";

const UPLOAD_ID_RE = /\/api\/uploads\/([0-9a-f-]{36})/i;

// Реальная жалоба: пока распознавание (vision.py) не закончилось, под
// картинкой висел отдельный абзац с текстом "⏳ ... обрабатывается…" —
// картинку саму по себе уже видно и можно сразу двигать/менять размер
// (ImageToolbar), но не было видно, что именно ЭТА картинка ещё в
// обработке. Тут — полупрозрачный оверлей со спиннером прямо поверх
// превью, как у карточек распознанного текста ниже. Плейсхолдер-абзац
// никуда не делся (тот же текст, который backend ищет и заменяет,
// vision.py::_replace_in_referencing_items) — просто визуально скрыт
// (см. extensions/HideImageProcessingPlaceholder.ts), не удалён: если
// убрать текст из документа целиком, backend'у нечего будет найти для
// замены на готовый результат.
export default function ResizableImageView({ node, editor, getPos }: NodeViewProps) {
  const { src, alt, width, align, rotation } = node.attrs as {
    src: string;
    alt?: string | null;
    width?: string | null;
    align?: string | null;
    rotation?: number;
  };

  const uploadId = src.match(UPLOAD_ID_RE)?.[1] ?? null;

  // "update" у TipTap — это ЛЮБОЕ изменение документа, не только своего
  // узла: NodeView по умолчанию не перерисовывается, когда меняется ЧУЖОЙ
  // узел (плейсхолдер-параграф в другом месте документа), а именно это и
  // нужно поймать — когда фоновый результат (vision.py) прилетает через
  // realtime и подменяет плейсхолдер, эта самая картинка должна убрать
  // оверлей, хотя её СОБСТВЕННЫЙ узел не менялся вовсе.
  const [, forceRerender] = useState(0);
  useEffect(() => {
    const onUpdate = () => forceRerender((n) => n + 1);
    editor.on("update", onUpdate);
    return () => {
      editor.off("update", onUpdate);
    };
  }, [editor]);

  const isProcessing =
    !!uploadId && editor.state.doc.textContent.includes(`⏳ Описание изображения ${uploadId} обрабатывается…`);

  const isSideways = rotation === 90 || rotation === 270;

  // Реальная жалоба: без явного width заметка полагалась на "случайное"
  // разрешение самого файла (inline-block + img width:100% схлопывается к
  // натуральному пиксельному размеру, если он меньше колонки редактора) —
  // горизонтальные и вертикальные фото с одного телефона визуально выходили
  // разной ширины, хотя пользователь ожидал ширину, зависящую от экрана, а
  // не от кадра. Дефолт — 100% колонки, как только явный width не задан.
  // Искл.: align=left/right — там schrink-to-fit к натуральному размеру
  // осознанное поведение (обтекание текстом маленькой картинки), не баг.
  const wrapperRef = useRef<HTMLDivElement>(null);
  const [containerWidth, setContainerWidth] = useState<number | null>(null);
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null);

  // Повёрнутая на 90/270° картинка меняет местами видимую ширину/высоту —
  // раньше layout-бокс оставался НЕповёрнутых размеров (чистый CSS
  // transform его не трогает), поэтому под повёрнутым фото оставался
  // огромный пустой промежуток (или, наоборот, наезд) — "как от
  // вертикального фото осталось", реальная жалоба. ResizeObserver + onLoad
  // дают точные натуральные пиксели без риска разъехаться на разных
  // экранах (сам файл не меняется), после чего высота wrapper'а и размер
  // картинки ДО поворота считаются так, чтобы после rotate() итог ровно
  // совпал с шириной колонки.
  useEffect(() => {
    if (!isSideways || !wrapperRef.current || typeof ResizeObserver === "undefined") return;
    const el = wrapperRef.current;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setContainerWidth(w);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [isSideways]);

  // Карточка распознанного текста сразу за картинкой — одно целое с ней:
  // низ картинки без скругления, карточка подхватывает ширину (см.
  // ImageOcrResultCard).
  useEditorTick(editor);
  const attachedBelow = nodeAfter(editor, getPos, node)?.type.name === "imageOcrResult";

  const wrapperStyle: CSSProperties = {};
  if (width) wrapperStyle.width = width;
  else if (align !== "left" && align !== "right") wrapperStyle.width = "100%";
  // Без явного выравнивания картинка по центру (замечание 23.10: «они
  // слева, некрасиво»), как и при align=center.
  if (align === "center" || !align) {
    wrapperStyle.display = "block";
    wrapperStyle.marginLeft = "auto";
    wrapperStyle.marginRight = "auto";
  } else if (align === "left") {
    wrapperStyle.float = "left";
    wrapperStyle.marginRight = "1em";
  } else if (align === "right") {
    wrapperStyle.float = "right";
    wrapperStyle.marginLeft = "1em";
  }

  let imgStyle: CSSProperties = rotation ? { transform: `rotate(${rotation}deg)` } : {};
  const radius = attachedBelow ? "rounded-t-2xl" : "rounded-2xl";
  let imgClassName = `block w-full ${radius}`;
  if (isSideways && containerWidth && natural) {
    const postW = containerWidth;
    const postH = (postW * natural.w) / natural.h;
    wrapperStyle.position = "relative";
    wrapperStyle.height = postH;
    wrapperStyle.overflow = "hidden";
    imgStyle = {
      position: "absolute",
      top: "50%",
      left: "50%",
      width: postH,
      height: postW,
      transform: `translate(-50%, -50%) rotate(${rotation}deg)`,
    };
    imgClassName = radius;
  } else if (isSideways) {
    // Ещё не знаем натуральные пиксели (картинка/измерение в процессе) —
    // временный фолбэк без обрезки, чтобы не мигать нулевым размером;
    // как только onLoad/ResizeObserver отработают, точный расчёт выше
    // возьмёт верх сам (не блокирует width/align — те уже применены выше).
    imgClassName = `block max-h-[70vh] w-auto max-w-full ${radius}`;
  }

  return (
    <NodeViewWrapper as="div" data-drag-handle draggable className={`max-w-full ${attachedBelow ? "mt-1 mb-0" : "my-1"}`}>
      <div ref={wrapperRef} className="relative inline-block max-w-full" style={wrapperStyle}>
        <img
          src={src}
          alt={alt || ""}
          onLoad={(e) => {
            const t = e.currentTarget;
            if (t.naturalWidth && t.naturalHeight) setNatural({ w: t.naturalWidth, h: t.naturalHeight });
          }}
          className={imgClassName}
          style={imgStyle}
        />
        {isProcessing && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-1.5 rounded bg-black/50 text-white">
            <Spinner size={18} />
            <span className="text-xs font-medium">Распознаём…</span>
          </div>
        )}
      </div>
    </NodeViewWrapper>
  );
}

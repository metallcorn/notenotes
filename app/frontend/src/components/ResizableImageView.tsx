import { useEffect, useState, type CSSProperties } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import Spinner from "./Spinner";

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
export default function ResizableImageView({ node, editor }: NodeViewProps) {
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

  // Первая версия при повороте на 90/270° игнорировала width/align
  // целиком (natural-размер с потолком по высоте экрана) — расчёт был в
  // том, что точно подогнать box под сохранённый width% (посчитанный под
  // НЕповёрнутую ориентацию) означало бы мерить натуральные пиксели
  // картинки через onLoad. На практике это читалось как «кнопки размера
  // сломались» — width/align реально переставали что-либо делать, пока
  // картинка повёрнута. Теперь width/align применяются к wrapper'у ВСЕГДА,
  // независимо от поворота; сам поворот — чистый CSS transform на <img>,
  // не влияющий на layout. Компромисс: на 90/270° повёрнутая картинка
  // может визуально выходить за рамки wrapper'а (transform не меняет
  // размер layout-бокса) — это осознанно менее аккуратно, чем идеальный
  // pixel-fit, но кнопки размера/выравнивания остаются рабочими всегда.
  const wrapperStyle: CSSProperties = {};
  if (width) wrapperStyle.width = width;
  if (align === "center") {
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

  const imgStyle: CSSProperties = rotation ? { transform: `rotate(${rotation}deg)` } : {};

  return (
    <NodeViewWrapper as="div" data-drag-handle draggable className="my-1 max-w-full">
      <div className="relative inline-block max-w-full" style={wrapperStyle}>
        <img
          src={src}
          alt={alt || ""}
          className="block w-full rounded"
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

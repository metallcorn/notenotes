import { useRef, useState } from "react";
import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { ChevronDown, ChevronUp, Pencil, RotateCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useReprocessUpload, useUpdateUploadTranscript } from "../api/hooks";
import { useAttachmentText } from "../lib/attachmentText";
import { ExpandedTextPanel, ReadFullscreenButton, RecognizedTextCopyButtons } from "./RecognizedTextView";
import Spinner from "./Spinner";

// Тот же спойлер-паттерн, что DocumentAttachmentCard.tsx использует для
// распознанного текста PDF — свёрнуто по умолчанию, картинка (обычный
// <img> перед этим узлом) уже видна сама по себе, текст нужен не всегда.
// Рендер и кнопки копирования — общий модуль RecognizedTextView.tsx, не
// копия: тот же текстовый формат (заголовки/таблицы/списки из промпта
// распознавания), та же пара "форматированная копия"/"копия как MD".
//
// uploadId/canReprocess — реальный запрос: OCR иногда ошибается (перепутанная
// цифра/буква), нужно и «распознать заново» (только для картинок/видео/PDF —
// эндпоинт /reprocess не умеет чистое аудио, поэтому canReprocess=false для
// голосовых записей и видео-аудио-расшифровок), и ручная правка текста —
// та работает для ЛЮБого источника этой карточки одинаково.
export default function ImageOcrResultCard({ node, updateAttributes }: NodeViewProps) {
  const { text: inlineText, uploadId, canReprocess } = node.attrs as {
    text: string;
    uploadId: string | null;
    canReprocess: boolean;
  };
  // Текст — из загрузки (lib/attachmentText.ts); data-text в узле есть
  // только у блоков старого формата.
  const { text } = useAttachmentText(uploadId, inlineText);
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(text);
  const cardRef = useRef<HTMLDivElement>(null);
  const reprocess = useReprocessUpload();
  const updateTranscript = useUpdateUploadTranscript();

  if (!text) return null;

  function startEdit() {
    setDraft(text);
    setEditing(true);
    setExpanded(true);
  }

  async function handleSave() {
    if (!uploadId) return;
    const value = draft.trim();
    if (!value) return;
    await updateTranscript.mutateAsync({ uploadId, text: value });
    // Блок старого формата держит свою копию текста в атрибуте, и она
    // главнее загрузки — после правки её надо убрать, иначе карточка
    // так и показывала бы прежний текст.
    if (inlineText) updateAttributes({ text: "" });
    await queryClient.invalidateQueries({ queryKey: ["upload-text", uploadId] });
    setEditing(false);
  }

  function handleReprocess() {
    if (!uploadId) return;
    // Есть что терять — текущий текст (в т.ч. только что исправленный
    // руками) заменится новым результатом, не факт что лучшим.
    if (window.confirm("Распознать заново? Текущий текст будет заменён новым результатом.")) {
      void reprocess.mutateAsync(uploadId);
    }
  }

  return (
    // Реальный корень бага (найден чтением исходников @tiptap/core): дело
    // не только в data-drag-handle — ГЛАВНОЕ, что сам HTML-атрибут
    // draggable=true на NodeViewWrapper браузер распознаёт независимо от
    // data-drag-handle. draggable теперь ТОЛЬКО на строке с кнопкой ниже.
    <NodeViewWrapper as="div" className="my-1 inline-block max-w-full">
      <div ref={cardRef} className="max-w-full rounded border bg-muted">
        <div data-drag-handle draggable className="flex items-center">
          <button
            onClick={() => setExpanded((v) => !v)}
            className="flex min-w-0 flex-1 items-center gap-1 px-3 py-1.5 text-left text-xs text-subtle hover:bg-muted-hover"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? "Скрыть распознанный текст" : "Показать распознанный текст"}
          </button>
          {uploadId && (
            <button
              onClick={startEdit}
              title="Исправить текст вручную"
              className="flex h-7 w-7 shrink-0 items-center justify-center text-subtle hover:bg-muted-hover hover:text-secondary"
            >
              <Pencil size={13} />
            </button>
          )}
          {uploadId && canReprocess && (
            <button
              onClick={handleReprocess}
              disabled={reprocess.isPending}
              title="Распознать заново"
              className="flex h-7 w-7 shrink-0 items-center justify-center text-subtle hover:bg-muted-hover hover:text-secondary disabled:opacity-50"
            >
              {reprocess.isPending ? <Spinner size={13} /> : <RotateCw size={13} />}
            </button>
          )}
          <RecognizedTextCopyButtons text={text} />
          <ReadFullscreenButton text={text} />
        </div>
        {expanded && editing && (
          <div className="border-t p-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={10}
              autoFocus
              className="w-full resize-y rounded border border-default p-2 font-mono text-xs text-primary focus:border-brand focus:outline-none"
            />
            <div className="mt-1.5 flex items-center justify-end gap-2">
              {updateTranscript.isError && (
                <span className="mr-auto text-xs text-danger">Не удалось сохранить</span>
              )}
              <button
                onClick={() => setEditing(false)}
                className="rounded px-2 py-1 text-xs text-subtle hover:bg-muted-hover"
              >
                Отмена
              </button>
              <button
                onClick={() => void handleSave()}
                disabled={updateTranscript.isPending || !draft.trim()}
                className="flex items-center gap-1 rounded bg-brand px-2.5 py-1 text-xs text-white hover:bg-brand/90 disabled:opacity-50"
              >
                {updateTranscript.isPending ? <Spinner size={12} /> : null}
                Сохранить
              </button>
            </div>
          </div>
        )}
        {expanded && !editing && <ExpandedTextPanel anchorRef={cardRef} text={text} />}
      </div>
    </NodeViewWrapper>
  );
}

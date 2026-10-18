import { createContext, useContext } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

// Распознанный текст вложения (OCR картинки, текстовый слой PDF, docx,
// расшифровка речи) с 18.10 живёт в самой загрузке, а не в заметке —
// см. app/backend/app/attachment_text.py, почему. Карточки вложений
// (DocumentAttachmentCard, ImageOcrResultCard, TicketAttachmentCard)
// берут его отсюда.
//
// Откуда брать — зависит от места: в приложении по id загрузки, на
// публичной странице — через токен шаринга (у анонима нет доступа к
// /uploads). Поэтому путь — контекст, а не константа.
export type AttachmentTextPath = (uploadId: string) => string;

export const AttachmentTextPathContext = createContext<AttachmentTextPath>((id) => `/uploads/${id}/text`);

// id загрузки по ссылке на файл. Шире, чем UPLOAD_ID_RE карточек: на
// публичной странице ссылка переписана в /api/public/{token}/uploads/{id}
// (PublicNotePage.tsx), и /api/uploads/ в ней уже нет.
const ANY_UPLOAD_ID_RE = /\/uploads\/([0-9a-f-]{36})/i;

export function attachmentTextId(url: string | null | undefined): string | null {
  return url?.match(ANY_UPLOAD_ID_RE)?.[1] ?? null;
}

interface UploadText {
  text: string;
  status: string;
}

// inlineText — текст из атрибута data-text блока старого формата. Он
// главнее: это либо единственная копия (загрузки уже нет), либо версия
// заметки, откаченная к состоянию до переезда.
export function useAttachmentText(uploadId: string | null | undefined, inlineText: string | undefined) {
  const path = useContext(AttachmentTextPathContext);
  const hasInline = !!inlineText;
  const query = useQuery<UploadText>({
    queryKey: ["upload-text", uploadId],
    queryFn: () => api.get<UploadText>(path(uploadId!)),
    enabled: !!uploadId && !hasInline,
    staleTime: 5 * 60 * 1000,
  });
  return {
    text: hasInline ? inlineText! : (query.data?.text ?? ""),
    // Пока текст грузится, карточка не должна успеть сказать «не
    // распознано» и показать кнопку «Распознать».
    loading: !hasInline && !!uploadId && query.isPending,
  };
}

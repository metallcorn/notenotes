import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import LinkExtension from "@tiptap/extension-link";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import Table from "@tiptap/extension-table";
import TableRow from "@tiptap/extension-table-row";
import TableCell from "@tiptap/extension-table-cell";
import TableHeader from "@tiptap/extension-table-header";
import { createLowlight, common } from "lowlight";
import { Markdown } from "tiptap-markdown";
import { ResizableImage } from "../extensions/ResizableImage";
import { Video } from "../extensions/Video";
import { Audio } from "../extensions/Audio";
import { LinkPreview } from "../extensions/LinkPreview";
import { DocumentAttachment } from "../extensions/DocumentAttachment";
import { TicketAttachment } from "../extensions/TicketAttachment";
import { InlineLinkFavicon } from "../extensions/InlineLinkFavicon";
import { DataRecognition } from "../extensions/DataRecognition";
import { ImageOcrResult } from "../extensions/ImageOcrResult";

const lowlight = createLowlight(common);

// Урезанное подмножество editorExtensions из NoteEditor.tsx — только
// display-узлы. Осознанно ИСКЛЮЧЕНЫ: SlashCommand (не нужен без
// редактирования), ReminderAnchor/UrlCheckAttachment (их карточки дёргают
// аутентифицированные мутации — "Напомнить"/"Обновить" ушли бы в 401 у
// анонима), Spacer/ProcessingPlaceholder/HideImageProcessingPlaceholder/
// TrailingParagraph (чисто про редактирование), DetectedAddressLinks
// (нужна storage-обвязка из NoteEditor, для read-only не критично).
// Кнопки внутри самих карточек (например, «Распознать заново» у
// DocumentAttachmentCard) технически всё ещё есть — клик анонимом
// закончится 401, но это не дыра безопасности, просто ошибка в UI;
// прятать их — отдельная доработка, не в этой версии.
const PUBLIC_VIEW_EXTENSIONS = [
  StarterKit.configure({ codeBlock: false }),
  CodeBlockLowlight.configure({ lowlight }),
  ResizableImage,
  Video,
  Audio,
  LinkPreview,
  DocumentAttachment,
  TicketAttachment,
  InlineLinkFavicon,
  DataRecognition,
  ImageOcrResult,
  LinkExtension.configure({ HTMLAttributes: { target: "_blank", rel: "noopener noreferrer" } }),
  Table.configure({ resizable: false }),
  TableRow,
  TableHeader,
  TableCell,
  Markdown.configure({ html: true, transformPastedText: true }),
];

export default function PublicNoteView({ content }: { content: string }) {
  // PUBLIC_VIEW_EXTENSIONS — модульная константа, стабильная сама по
  // себе (та же причина стабильности важна, что у editorExtensions в
  // NoteEditor.tsx, просто здесь для этого не нужен useMemo). Компонент
  // монтируется только когда content уже известен (см. PublicNotePage.tsx)
  // — обновлять содержимое повторно не требуется, оно неизменно на весь
  // срок жизни read-only просмотра.
  const editor = useEditor({
    extensions: PUBLIC_VIEW_EXTENSIONS,
    content,
    editable: false,
  });

  return (
    <div className="prose prose-sm max-w-none">
      <EditorContent editor={editor} />
    </div>
  );
}

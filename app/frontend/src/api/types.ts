export interface User {
  id: string;
  username: string;
  name: string;
  created_at: string;
  custom_instructions: string;
  disabled_tools: string[];
  tts_voice: string;
  auto_process_uploads: boolean;
  llm_provider: string;
  timezone: string;
}

export interface InviteCode {
  id: string;
  code: string;
  created_at: string;
  expires_at: string;
  used_at: string | null;
}

export interface Skill {
  name: string;
  label: string;
  description: string;
  toggleable: boolean;
  enabled: boolean;
}

export interface Space {
  id: string;
  name: string;
  owner_id: string;
  created_at: string;
  is_vault: boolean;
  is_public_pages: boolean;
}

export interface VaultUnlockInfo {
  vault_salt: string;
  vault_verifier: string;
}

export interface SpaceMember {
  user_id: string;
  username: string;
  name: string;
  joined_at: string;
}

export interface SpaceInvite {
  id: string;
  token: string;
  created_at: string;
  expires_at: string;
  revoked_at: string | null;
}

export interface Folder {
  id: string;
  space_id: string;
  parent_id: string | null;
  name: string;
  created_at: string;
}

export interface Tag {
  id: string;
  name: string;
  created_at: string;
}

export interface ItemTag extends Tag {
  auto: boolean;
}

export interface Item {
  id: string;
  space_id: string;
  folder_id: string | null;
  author_id: string;
  material_type: string;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
  tags: ItemTag[];
  icon: string | null;
  color: string | null;
  pinned: boolean;
  deleted_at: string | null;
  // Сейф (ТЗ §16.2): для сейфовых заметок title/content на сервере — заглушка
  // "🔒 Зашифровано", реальный текст — здесь, зашифрован (см. vaultCrypto.ts).
  // Прозрачно расшифровывается/зашифровывается в api/hooks.ts, компоненты
  // редактирования этого поля не видят.
  vault?: { title?: { iv: string; ciphertext: string }; content?: { iv: string; ciphertext: string } } | null;
  // Найденные LLM адреса (app/autotag.py) — extensions/DetectedAddressLinks.ts
  // ищет "text" дословно в документе и подсвечивает ссылкой на карту.
  detected_addresses: { text: string; query: string }[];
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface DialogMessage {
  id: string;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  tool_calls: ToolCall[];
  display_tool_calls: ToolCall[];
  tool_call_id: string | null;
  name: string | null;
  suggested_replies: string[];
  created_at: string;
  // Синтетическая сводка более ранней части истории (сжатие диалога) —
  // обычная assistant-запись с этими двумя флагами. snapshot_id указывает
  // на Dialog.compaction_snapshots, по нему фронт откатывает сжатие.
  is_summary: boolean;
  snapshot_id: string | null;
}

export interface CompactionSnapshot {
  id: string;
  created_at: string;
  message_count: number;
}

export interface DialogSummary {
  id: string;
  space_id: string;
  space_name: string;
  title: string;
  created_at: string;
  updated_at: string;
  // Только у скретч-диалогов заметки (see NoteAssistantModal.tsx) — первое
  // сообщение пользователя коротко, чтобы отличать их друг от друга в списке.
  preview?: string | null;
}

export interface Dialog extends DialogSummary {
  messages: DialogMessage[];
  compaction_snapshots: CompactionSnapshot[];
}

export interface ListEntry {
  id: string;
  text: string;
  checked: boolean;
  created_at: string;
}

export interface ListDetail {
  id: string;
  space_id: string;
  folder_id: string | null;
  title: string;
  entries: ListEntry[];
  created_at: string;
  updated_at: string;
}

export interface TableColumn {
  id: string;
  name: string;
  type: string;
}

export interface TableRow {
  id: string;
  cells: Record<string, string>;
  created_at: string;
}

export interface TableDetail {
  id: string;
  space_id: string;
  folder_id: string | null;
  title: string;
  columns: TableColumn[];
  rows: TableRow[];
  created_at: string;
  updated_at: string;
}

export interface AssistantMemoryFact {
  id: string;
  content: string;
  created_at: string;
}

export interface UploadResult {
  id: string;
  url: string;
  filename: string;
  content_type: string;
  pdf_text: string | null;
  pdf_ocr_queued: boolean;
  preview_text: string | null;
  has_thumbnail: boolean;
  size_bytes: number;
}

// Виджет «Проверить по ссылке» (UrlCheckCard.tsx) — состояние читается
// с бэкенда по id (url_check_widgets), не хранится в content заметки.
export interface UrlCheckWidgetState {
  url: string;
  fields: { path: string; label: string }[];
  last_result: string | null;
  last_fetched_at: string | null;
  last_status: number | null;
  has_credentials: boolean;
}

// Состояние постоянного виджета доставки (DeliveryWidgetCard.tsx). result —
// уже распарсенный нормализованный ответ delivery.track (форма DeliveryData
// из DeliveryCard), null если последний опрос не удался.
export interface DeliveryWidgetState {
  carrier: string;
  tracking_number: string;
  result: Record<string, unknown> | null;
  last_fetched_at: string | null;
}

export interface ItemVersion {
  id: string;
  title: string;
  content: string;
  author_id: string | null;
  created_at: string;
}

// Автокомплит вставки ссылки на другую заметку (NoteLink.ts,
// NoteLinkSuggestionList.tsx) — GET /api/items/search-titles.
export interface ItemTitleSearchResult {
  id: string;
  title: string;
  space_id: string;
  material_type: string;
}

export interface LinkPreviewData {
  url: string;
  title: string | null;
  description: string | null;
  image_url: string | null;
  favicon_url: string | null;
  fetch_failed: boolean;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  body: string;
  payload: Record<string, unknown>;
  read_at: string | null;
  created_at: string;
  trigger_at: string | null;
  resolved_at: string | null;
}

// Дата/событие, найденное LLM внутри заметки (app/autotag.py) — пассивная
// запись без доставки (не Notification): только для ActivityView.
export interface DetectedEvent {
  item_id: string;
  space_id: string;
  item_title: string;
  event_title: string;
  event_at: string;
}

// Публичные страницы (routers/public.py) — ShareNoteModal.tsx.
export interface ShareInfo {
  is_public: boolean;
  share_token: string | null;
  has_password: boolean;
  share_expires_at: string | null;
  share_single_use: boolean;
  share_used_at: string | null;
}

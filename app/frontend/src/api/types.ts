export interface User {
  id: string;
  username: string;
  name: string;
  created_at: string;
  custom_instructions: string;
  disabled_tools: string[];
  tts_voice: string;
  auto_process_uploads: boolean;
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
  tool_call_id: string | null;
  name: string | null;
  suggested_replies: string[];
  created_at: string;
}

export interface DialogSummary {
  id: string;
  space_id: string;
  space_name: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface Dialog extends DialogSummary {
  messages: DialogMessage[];
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
}

export interface ItemVersion {
  id: string;
  title: string;
  content: string;
  author_id: string | null;
  created_at: string;
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

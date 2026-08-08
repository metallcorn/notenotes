import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  AssistantMemoryFact,
  Dialog,
  DialogSummary,
  Folder,
  Item,
  ItemVersion,
  ListDetail,
  Notification,
  Skill,
  Space,
  Tag,
  UploadResult,
  User,
} from "./types";

// --- auth --------------------------------------------------------------

export function useMe() {
  return useQuery<User>({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/auth/me"),
    retry: false,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { username: string; password: string }) => api.post<User>("/auth/login", payload),
    onSuccess: (user) => qc.setQueryData(["me"], user),
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { username: string; password: string; name: string }) =>
      api.post<User>("/auth/register", payload),
    onSuccess: (user) => qc.setQueryData(["me"], user),
  });
}

export function useUpdateCustomInstructions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (custom_instructions: string) => api.patch<User>("/auth/me", { custom_instructions }),
    onSuccess: (user) => qc.setQueryData(["me"], user),
  });
}

export function useSkills() {
  return useQuery<Skill[]>({
    queryKey: ["skills"],
    queryFn: () => api.get<Skill[]>("/skills"),
  });
}

export function useUpdateDisabledTools() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (disabled_tools: string[]) => api.patch<User>("/auth/me", { disabled_tools }),
    onSuccess: (user) => {
      qc.setQueryData(["me"], user);
      qc.invalidateQueries({ queryKey: ["skills"] });
    },
  });
}

export function useUpdateTtsVoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tts_voice: string) => api.patch<User>("/auth/me", { tts_voice }),
    onSuccess: (user) => qc.setQueryData(["me"], user),
  });
}

export function useAiTransform() {
  return useMutation({
    mutationFn: (payload: { action: "summarize" | "reformat" | "rewrite"; text: string; instruction?: string }) =>
      api.post<{ result: string }>("/ai/transform", payload),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/auth/logout"),
    onSuccess: () => qc.setQueryData(["me"], undefined),
  });
}

// --- spaces --------------------------------------------------------------

export function useSpaces() {
  return useQuery<Space[]>({ queryKey: ["spaces"], queryFn: () => api.get<Space[]>("/spaces") });
}

export function useCreateSpace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<Space>("/spaces", { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spaces"] }),
  });
}

export function useUpdateSpace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.patch<Space>(`/spaces/${id}`, { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spaces"] }),
  });
}

// --- folders --------------------------------------------------------------

export function useFolders(spaceId: string | undefined) {
  return useQuery<Folder[]>({
    queryKey: ["folders", spaceId],
    queryFn: () => api.get<Folder[]>(`/folders?space_id=${spaceId}`),
    enabled: !!spaceId,
  });
}

export function useCreateFolder(spaceId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string; parent_id?: string | null }) =>
      api.post<Folder>("/folders", { space_id: spaceId, ...payload }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["folders", spaceId] }),
  });
}

export function useUpdateFolder(spaceId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...payload }: { id: string; name?: string; parent_id?: string | null }) =>
      api.patch<Folder>(`/folders/${id}`, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["folders", spaceId] }),
  });
}

export function useDeleteFolder(spaceId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/folders/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["folders", spaceId] });
      qc.invalidateQueries({ queryKey: ["items", spaceId] });
    },
  });
}

// --- tags --------------------------------------------------------------

export function useTags() {
  return useQuery<Tag[]>({ queryKey: ["tags"], queryFn: () => api.get<Tag[]>("/tags") });
}

export function useCreateTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.post<Tag>("/tags", { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tags"] }),
  });
}

export function useRenameTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => api.patch<Tag>(`/tags/${id}`, { name }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tags"] }),
  });
}

export function useMergeTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, targetTagId }: { id: string; targetTagId: string }) =>
      api.post<Tag>(`/tags/${id}/merge`, { target_tag_id: targetTagId }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["items"] });
    },
  });
}

export function useDeleteTag() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/tags/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tags"] });
      qc.invalidateQueries({ queryKey: ["items"] });
    },
  });
}

// --- items --------------------------------------------------------------

export function useItems(spaceId: string | undefined, folderId?: string | null, tagId?: string | null) {
  return useQuery<Item[]>({
    queryKey: ["items", spaceId, folderId ?? null, tagId ?? null],
    queryFn: () => {
      const params = new URLSearchParams({ space_id: spaceId! });
      if (folderId) params.set("folder_id", folderId);
      if (tagId) params.set("tag_id", tagId);
      return api.get<Item[]>(`/items?${params.toString()}`);
    },
    enabled: !!spaceId,
  });
}

export function useItem(id: string | undefined) {
  return useQuery<Item>({
    queryKey: ["item", id],
    queryFn: () => api.get<Item>(`/items/${id}`),
    enabled: !!id,
  });
}

export function useCreateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { space_id: string; folder_id?: string | null; title?: string; content?: string }) =>
      api.post<Item>("/items", payload),
    onSuccess: (item) => qc.invalidateQueries({ queryKey: ["items", item.space_id] }),
  });
}

export function useUpdateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...payload
    }: {
      id: string;
      title?: string;
      content?: string;
      folder_id?: string | null;
      icon?: string | null;
      color?: string | null;
      pinned?: boolean;
    }) => api.patch<Item>(`/items/${id}`, payload),
    onSuccess: (item) => {
      qc.setQueryData(["item", item.id], item);
      qc.invalidateQueries({ queryKey: ["items", item.space_id] });
    },
  });
}

export function useDeleteItem(spaceId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/items/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["items", spaceId] }),
  });
}

export function useItemVersions(itemId: string | undefined) {
  return useQuery<ItemVersion[]>({
    queryKey: ["item-versions", itemId],
    queryFn: () => api.get<ItemVersion[]>(`/items/${itemId}/versions`),
    enabled: !!itemId,
  });
}

export function useRevertVersion(itemId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (versionId: string) => api.post<Item>(`/items/${itemId}/versions/${versionId}/revert`),
    onSuccess: (item) => {
      qc.setQueryData(["item", itemId], item);
      qc.invalidateQueries({ queryKey: ["item-versions", itemId] });
      qc.invalidateQueries({ queryKey: ["items", item.space_id] });
    },
  });
}

export function useAddItemTag(itemId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tagId: string) => api.post<Item>(`/items/${itemId}/tags/${tagId}`),
    onSuccess: (item) => {
      qc.setQueryData(["item", itemId], item);
      qc.invalidateQueries({ queryKey: ["items", item.space_id] });
    },
  });
}

export function useRemoveItemTag(itemId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (tagId: string) => api.delete<Item>(`/items/${itemId}/tags/${tagId}`),
    onSuccess: (item) => {
      qc.setQueryData(["item", itemId], item);
      qc.invalidateQueries({ queryKey: ["items", item.space_id] });
    },
  });
}

export function useSuggestTags(itemId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Item>(`/items/${itemId}/suggest-tags`),
    onSuccess: (item) => {
      qc.setQueryData(["item", itemId], item);
      qc.invalidateQueries({ queryKey: ["items", item.space_id] });
    },
  });
}

// --- корзина --------------------------------------------------------------

export function useTrash(spaceId: string | undefined) {
  return useQuery<Item[]>({
    queryKey: ["trash", spaceId],
    queryFn: () => api.get<Item[]>(`/items/trash/list?space_id=${spaceId}`),
    enabled: !!spaceId,
  });
}

export function useRestoreItem(spaceId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Item>(`/items/${id}/restore`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trash", spaceId] });
      qc.invalidateQueries({ queryKey: ["items", spaceId] });
    },
  });
}

export function usePermanentDeleteItem(spaceId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/items/${id}/permanent`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["trash", spaceId] }),
  });
}

// --- ассистент (диалоги) ---------------------------------------------------

// Без space_id — сразу по всем спейсам пользователя (раньше чаты с
// ассистентом были строго разделены по спейсам, как заметки — жалоба:
// разговор с ботом в Telegram (свой спейс "Telegram") не находился, пока
// не переключишься именно на него; теперь один список на всё).
export function useDialogs() {
  return useQuery<DialogSummary[]>({
    queryKey: ["dialogs", "all"],
    queryFn: () => api.get<DialogSummary[]>(`/dialogs`),
  });
}

export function useDialog(dialogId: string | undefined) {
  return useQuery<Dialog>({
    queryKey: ["dialog", dialogId],
    queryFn: () => api.get<Dialog>(`/dialogs/${dialogId}`),
    enabled: !!dialogId,
  });
}

// Без space_id — бэкенд сам выбирает "домашний" спейс пользователя
// (ассистент не привязан к одному спейсу с точки зрения пользователя, см.
// _default_space_id в routers/dialogs.py).
export function useCreateDialog() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Dialog>("/dialogs", {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dialogs"] }),
  });
}

export function useSendDialogMessage(dialogId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ content, signal }: { content: string; signal?: AbortSignal }) =>
      api.post<Dialog>(`/dialogs/${dialogId}/messages`, { content }, signal),
    onSuccess: (dialog) => {
      qc.setQueryData(["dialog", dialogId], dialog);
      qc.invalidateQueries({ queryKey: ["dialogs", dialog.space_id] });
      // Ассистент меняет заметки/списки/папки/теги через свои тулы на
      // бэкенде, в обход обычных мутаций фронтенда — без этого сайдбар не
      // узнаёт об изменениях, пока страницу не перезагрузят вручную
      // (реальная жалоба). Тул мог задеть любой спейс пользователя (ТЗ
      // §10a — не только текущий), поэтому инвалидируем широко, не по
      // конкретному space_id.
      qc.invalidateQueries({ queryKey: ["items"] });
      qc.invalidateQueries({ queryKey: ["folders"] });
      qc.invalidateQueries({ queryKey: ["tags"] });
    },
  });
}

export function useDeleteDialogMessage(dialogId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (messageId: string) => api.delete<Dialog>(`/dialogs/${dialogId}/messages/${messageId}`),
    onSuccess: (dialog) => {
      qc.setQueryData(["dialog", dialogId], dialog);
      qc.invalidateQueries({ queryKey: ["dialogs", dialog.space_id] });
    },
  });
}

// --- списки --------------------------------------------------------------

export function useList(id: string | undefined) {
  return useQuery<ListDetail>({
    queryKey: ["list", id],
    queryFn: () => api.get<ListDetail>(`/lists/${id}`),
    enabled: !!id,
  });
}

export function useCreateList() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { space_id: string; folder_id?: string | null; title?: string }) =>
      api.post<ListDetail>("/lists", payload),
    onSuccess: (list) => qc.invalidateQueries({ queryKey: ["items", list.space_id] }),
  });
}

export function useAddListEntry(listId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => api.post<ListDetail>(`/lists/${listId}/entries`, { text }),
    onSuccess: (list) => {
      qc.setQueryData(["list", listId], list);
      qc.invalidateQueries({ queryKey: ["items", list.space_id] });
    },
  });
}

export function useUpdateListEntry(listId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ entryId, text, checked }: { entryId: string; text?: string; checked?: boolean }) =>
      api.patch<ListDetail>(`/lists/${listId}/entries/${entryId}`, { text, checked }),
    onSuccess: (list) => qc.setQueryData(["list", listId], list),
  });
}

export function useDeleteListEntry(listId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (entryId: string) => api.delete<ListDetail>(`/lists/${listId}/entries/${entryId}`),
    onSuccess: (list) => qc.setQueryData(["list", listId], list),
  });
}

// --- память ассистента ------------------------------------------------------

export function useMemories() {
  return useQuery<AssistantMemoryFact[]>({
    queryKey: ["memories"],
    queryFn: () => api.get<AssistantMemoryFact[]>("/memories"),
  });
}

export function useDeleteMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/memories/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["memories"] }),
  });
}

// --- голос (ASR/TTS) --------------------------------------------------------

export function useTranscribeAudio() {
  return useMutation({
    mutationFn: async (blob: Blob) => {
      const form = new FormData();
      form.append("audio", blob, "voice-message.webm");
      return api.post<{ text: string }>("/voice/transcribe", form);
    },
  });
}

export function useSpeak() {
  return useMutation({
    mutationFn: (text: string) => api.postForBlob("/voice/speak", { text }),
  });
}

// --- search --------------------------------------------------------------

export function useSearch(q: string) {
  return useQuery<Item[]>({
    queryKey: ["search", q],
    queryFn: () => api.get<Item[]>(`/search?q=${encodeURIComponent(q)}`),
    enabled: q.trim().length > 0,
  });
}

// --- uploads --------------------------------------------------------------

export function useUploadFile(spaceId: string | undefined) {
  return useMutation({
    mutationFn: async ({ file, onProgress }: { file: File; onProgress?: (pct: number) => void }) => {
      const form = new FormData();
      form.append("file", file);
      return api.uploadWithProgress<UploadResult>(`/uploads?space_id=${spaceId}`, form, onProgress);
    },
  });
}

// Повторный запуск OCR/расшифровки — для файлов, загруженных до появления
// vision.py/transcription.py, или если распознавание не задалось с первого
// раза. Результат прилетает не из ответа мутации, а тем же путём, что и при
// обычной загрузке — фоновый воркер заменит плейсхолдер в content заметки,
// и WS-нотификация ("items") сама обновит открытую заметку.
export function useReprocessUpload() {
  return useMutation({
    mutationFn: (uploadId: string) => api.post(`/uploads/${uploadId}/reprocess`),
  });
}

// --- telegram ---------------------------------------------------------------

export function useTelegramStatus() {
  return useQuery<{ linked: boolean }>({
    queryKey: ["telegram-status"],
    queryFn: () => api.get<{ linked: boolean }>("/telegram/status"),
  });
}

export function useTelegramLinkCode() {
  return useMutation({
    mutationFn: () => api.post<{ deep_link: string; expires_at: string }>("/telegram/link-code"),
  });
}

export function useTelegramUnlink() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.delete("/telegram/link"),
    onSuccess: () => qc.setQueryData(["telegram-status"], { linked: false }),
  });
}

// --- notifications ---------------------------------------------------------

export function useNotifications() {
  return useQuery<Notification[]>({
    queryKey: ["notifications"],
    queryFn: () => api.get<Notification[]>("/notifications"),
    // Раз в минуту, не в 5 — напоминания ассистента (create_reminder)
    // "проявляются" ровно фильтром по trigger_at в выборке, без пуша;
    // 5 минут ощущались бы как заметное опоздание для "напомни в 21:00".
    refetchInterval: 60 * 1000,
  });
}

export function useMarkNotificationRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Notification>(`/notifications/${id}/read`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>("/notifications/read-all"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

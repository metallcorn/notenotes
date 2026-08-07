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

export function useDialogs(spaceId: string | undefined) {
  return useQuery<DialogSummary[]>({
    queryKey: ["dialogs", spaceId],
    queryFn: () => api.get<DialogSummary[]>(`/dialogs?space_id=${spaceId}`),
    enabled: !!spaceId,
  });
}

export function useDialog(dialogId: string | undefined) {
  return useQuery<Dialog>({
    queryKey: ["dialog", dialogId],
    queryFn: () => api.get<Dialog>(`/dialogs/${dialogId}`),
    enabled: !!dialogId,
  });
}

export function useCreateDialog(spaceId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Dialog>("/dialogs", { space_id: spaceId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dialogs", spaceId] }),
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
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api.post<UploadResult>(`/uploads?space_id=${spaceId}`, form);
    },
  });
}

// --- notifications ---------------------------------------------------------

export function useNotifications() {
  return useQuery<Notification[]>({
    queryKey: ["notifications"],
    queryFn: () => api.get<Notification[]>("/notifications"),
    refetchInterval: 5 * 60 * 1000,
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

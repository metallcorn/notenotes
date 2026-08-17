import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "./client";
import type { EncryptedField } from "../lib/vaultCrypto";
import {
  createVerifier,
  decryptField,
  decryptFileBytes,
  deriveKey,
  encryptField,
  encryptFileBlob,
  generateSalt,
} from "../lib/vaultCrypto";
import { getVaultKey, unlockVault, useVaultUnlocked } from "../lib/vaultSession";
import type {
  AssistantMemoryFact,
  DetectedEvent,
  Dialog,
  DialogSummary,
  Folder,
  InviteCode,
  Item,
  ItemVersion,
  LinkPreviewData,
  ListDetail,
  Notification,
  Skill,
  Space,
  Tag,
  UploadResult,
  UrlCheckFetchResult,
  User,
  VaultUnlockInfo,
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
    mutationFn: (payload: { username: string; password: string; name: string; invite_code: string }) =>
      api.post<User>("/auth/register", payload),
    onSuccess: (user) => qc.setQueryData(["me"], user),
  });
}

// Инвайт-коды регистрации — создаёт существующий пользователь в настройках
// (реальный запрос: сам выдаёт код тому, кого добавляет, вместо единого
// секрета в vault). Одноразовые, живут 7 дней.
export function useCreateInviteCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<InviteCode>("/auth/invite-codes"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["invite-codes"] }),
  });
}

export function useInviteCodes() {
  return useQuery<InviteCode[]>({
    queryKey: ["invite-codes"],
    queryFn: () => api.get<InviteCode[]>("/auth/invite-codes"),
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

export function useUpdateAutoProcessUploads() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (auto_process_uploads: boolean) => api.patch<User>("/auth/me", { auto_process_uploads }),
    onSuccess: (user) => qc.setQueryData(["me"], user),
  });
}

export function useUpdateLlmProvider() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (llm_provider: string) => api.patch<User>("/auth/me", { llm_provider }),
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
    mutationFn: (payload: { name: string; is_vault?: boolean; vault_salt?: string; vault_verifier?: string }) =>
      api.post<Space>("/spaces", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["spaces"] }),
  });
}

export function useVaultUnlockInfo(spaceId: string | undefined) {
  return useQuery<VaultUnlockInfo>({
    queryKey: ["vault-unlock-info", spaceId],
    queryFn: () => api.get<VaultUnlockInfo>(`/spaces/${spaceId}/vault-unlock-info`),
    enabled: !!spaceId,
    staleTime: Infinity,
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
//
// Сейф (ТЗ §16.2): сервер хранит только шифротекст (title/content —
// заглушка "🔒 Зашифровано", реальный текст в item.vault). Расшифровка/
// шифрование происходят прозрачно здесь — NoteEditor.tsx и остальные
// компоненты получают/отправляют обычный plaintext, как будто шифрования
// нет вовсе (см. план — "единственный способ не переписывать самый
// большой файл в проекте под крипто-логику").

const VAULT_PLACEHOLDER = "🔒 Зашифровано";

// Вложения (картинки/видео/аудио/документы) встраиваются в content прямыми
// ссылками на /api/uploads/{id} — сам URL не секрет (непрозрачный id), а
// вот БАЙТЫ по этому URL для сейфа зашифрованы на диске (useUploadFile
// ниже). Вместо того чтобы переписывать каждое TipTap-расширение
// (Image/Video/Audio/DocumentAttachment) под расшифровку конкретного узла
// — подменяем такие ссылки на расшифрованные blob:-URL ПРЯМО В ТЕКСТЕ
// content, до того как он попадёт в редактор: редактор и все карточки
// вложений остаются полностью не в курсе шифрования, ссылка просто уже
// готова к показу (тот же принцип прозрачности, что и у title/content).
const UPLOAD_URL_RE = /\/api\/uploads\/[0-9a-f-]{36}/gi;
const decryptedBlobUrlCache = new Map<string, string>();

async function decryptUploadUrlsInContent(content: string, key: CryptoKey): Promise<string> {
  const urls = Array.from(new Set(content.match(UPLOAD_URL_RE) ?? []));
  if (urls.length === 0) return content;
  const replacements = await Promise.all(
    urls.map(async (url): Promise<[string, string]> => {
      const cached = decryptedBlobUrlCache.get(url);
      if (cached) return [url, cached];
      try {
        // url — уже полный путь вида "/api/uploads/{id}" (как он лежит в
        // content), не относительный кусок для api.get — обычный fetch, не
        // client.ts-обёртка.
        const res = await fetch(url, { credentials: "include" });
        if (!res.ok) return [url, url];
        const contentType = res.headers.get("content-type") || "application/octet-stream";
        const encrypted = await res.arrayBuffer();
        const bytes = await decryptFileBytes(key, encrypted);
        const blobUrl = URL.createObjectURL(new Blob([bytes], { type: contentType }));
        decryptedBlobUrlCache.set(url, blobUrl);
        return [url, blobUrl];
      } catch {
        return [url, url];
      }
    }),
  );
  let result = content;
  for (const [url, blobUrl] of replacements) {
    result = result.split(url).join(blobUrl);
  }
  return result;
}

async function decryptItemVault(item: Item): Promise<Item> {
  if (!item.vault) return item;
  const key = getVaultKey(item.space_id);
  if (!key) return item;
  const vault = item.vault;
  const [title, rawContent] = await Promise.all([
    vault.title ? decryptField(key, vault.title) : Promise.resolve(item.title),
    vault.content ? decryptField(key, vault.content) : Promise.resolve(item.content),
  ]);
  const content = await decryptUploadUrlsInContent(rawContent, key);
  return { ...item, title, content };
}

export function useItems(spaceId: string | undefined, folderId?: string | null, tagId?: string | null) {
  const raw = useQuery<Item[]>({
    queryKey: ["items", spaceId ?? null, folderId ?? null, tagId ?? null],
    queryFn: () => {
      const params = new URLSearchParams();
      // Без spaceId — кросс-спейсовый запрос по тегу (тег не привязан к
      // одному спейсу, см. routers/items.py:list_items).
      if (spaceId) params.set("space_id", spaceId);
      if (folderId) params.set("folder_id", folderId);
      if (tagId) params.set("tag_id", tagId);
      return api.get<Item[]>(`/items?${params.toString()}`);
    },
    enabled: !!spaceId || !!tagId,
  });
  // useSyncExternalStore-подписка на разблокировку — без неё список так и
  // остался бы с заглушками после ввода пароля, до следующего невязанного
  // ре-рендера.
  const unlocked = useVaultUnlocked(spaceId);
  const [data, setData] = useState<Item[] | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!raw.data) {
        setData(undefined);
        return;
      }
      const resolved = await Promise.all(raw.data.map(decryptItemVault));
      if (!cancelled) setData(resolved);
    })();
    return () => {
      cancelled = true;
    };
  }, [raw.data, unlocked]);
  return { ...raw, data };
}

// Кросс-спейсовая лента "Недавнее" для ActivityView — /items/recent, не
// /items (тот требует spaceId или tagId, тут явно "все спейсы сразу").
// Сейф исключён на сервере (routers/items.py) — расшифровывать тут нечего.
export function useRecentItems() {
  return useQuery<Item[]>({
    queryKey: ["items", "recent"],
    queryFn: () => api.get<Item[]>("/items/recent"),
  });
}

// Даты/события, найденные LLM внутри заметок (app/autotag.py) — для
// ActivityView, пассивные, без доставки (см. DetectedEvent в types.ts).
export function useDetectedEvents() {
  return useQuery<DetectedEvent[]>({
    queryKey: ["items", "detected-events"],
    queryFn: () => api.get<DetectedEvent[]>("/items/detected-events"),
  });
}

// Убрать ложное срабатывание детектора дат — тот же принцип, что удаление
// авто-тега (ТЗ §8.2): предлагает, не перекладывает молча.
export function useDismissDetectedEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ itemId, eventAt, eventTitle }: { itemId: string; eventAt: string; eventTitle: string }) =>
      api.post(`/items/${itemId}/detected-events/dismiss`, { event_at: eventAt, event_title: eventTitle }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["items", "detected-events"] }),
  });
}

export function useItem(id: string | undefined) {
  const raw = useQuery<Item>({
    queryKey: ["item", id],
    queryFn: () => api.get<Item>(`/items/${id}`),
    enabled: !!id,
  });
  const unlocked = useVaultUnlocked(raw.data?.space_id);
  const [data, setData] = useState<Item | undefined>(undefined);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!raw.data) {
        setData(undefined);
        return;
      }
      const resolved = await decryptItemVault(raw.data);
      if (!cancelled) setData(resolved);
    })();
    return () => {
      cancelled = true;
    };
  }, [raw.data, unlocked]);
  return { ...raw, data };
}

export function useCreateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      space_id: string;
      folder_id?: string | null;
      title?: string;
      content?: string;
    }) => {
      const key = getVaultKey(payload.space_id);
      if (!key) return api.post<Item>("/items", payload);
      const vault: { title?: EncryptedField; content?: EncryptedField } = {};
      const body: typeof payload & { vault?: typeof vault } = { ...payload };
      if (payload.title !== undefined) {
        vault.title = await encryptField(key, payload.title);
        body.title = VAULT_PLACEHOLDER;
      }
      if (payload.content !== undefined) {
        vault.content = await encryptField(key, payload.content);
        body.content = VAULT_PLACEHOLDER;
      }
      body.vault = vault;
      return api.post<Item>("/items", body);
    },
    onSuccess: (item) => qc.invalidateQueries({ queryKey: ["items", item.space_id] }),
  });
}

export function useUpdateItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
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
    }) => {
      const cached = qc.getQueryData<Item>(["item", id]);
      const key = cached ? getVaultKey(cached.space_id) : undefined;
      if (!key || (payload.title === undefined && payload.content === undefined)) {
        return api.patch<Item>(`/items/${id}`, payload);
      }
      // Незашифрованное поле (например, только title меняется) сохраняет
      // старый шифротекст, а не теряет его — иначе сохранение одного поля
      // стёрло бы шифротекст другого.
      const vault: { title?: EncryptedField; content?: EncryptedField } = { ...cached?.vault };
      const body: typeof payload & { vault?: typeof vault } = { ...payload };
      if (payload.title !== undefined) {
        vault.title = await encryptField(key, payload.title);
        body.title = VAULT_PLACEHOLDER;
      }
      if (payload.content !== undefined) {
        vault.content = await encryptField(key, payload.content);
        body.content = VAULT_PLACEHOLDER;
      }
      body.vault = vault;
      return api.patch<Item>(`/items/${id}`, body);
    },
    onSuccess: (item) => {
      qc.setQueryData(["item", item.id], item);
      qc.invalidateQueries({ queryKey: ["items", item.space_id] });
    },
  });
}

export function useMoveItemSpace() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, space_id }: { id: string; space_id: string }) =>
      api.post<Item>(`/items/${id}/move`, { space_id }),
    onSuccess: (item) => {
      qc.setQueryData(["item", item.id], item);
      // Широко, а не по конкретному spaceId: перенос задевает СРАЗУ два
      // спейса (старый теряет заметку, новый приобретает) — префиксное
      // совпадение ["items"] инвалидирует списки обоих разом.
      qc.invalidateQueries({ queryKey: ["items"] });
    },
  });
}

// Перенос заметки (с плейнтекстом, из обычного спейса) в сейф — в отличие
// от обычного move, требует полного шифрования на клиенте ДО самого
// переноса (backend отклоняет move в сейф без properties.vault, см.
// routers/items.py). Только заметки — списки/билеты не шифруются вообще
// (properties устроены иначе, чем title/content), эта же проверка
// повторена на бэкенде.
export function useMigrateItemToVault() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ item, targetSpaceId }: { item: Item; targetSpaceId: string }) => {
      const key = getVaultKey(targetSpaceId);
      if (!key) throw new Error("Сейф заблокирован");

      // 1. Вложенные файлы — перезаливаем уже зашифрованными в целевой
      // сейф, ссылки в content переписываем на новые id. Старые id
      // запоминаем, чтобы после успешного переноса удалить их
      // НЕзашифрованные оригиналы (не ждать 24ч грейс-период cleanup.py —
      // документ с перс. данными не должен лежать plaintext лишние часы).
      const uploadUrls = Array.from(new Set(item.content.match(UPLOAD_URL_RE) ?? []));
      let content = item.content;
      const oldUploadIds: string[] = [];
      for (const url of uploadUrls) {
        const res = await fetch(url, { credentials: "include" });
        if (!res.ok) continue;
        const contentType = res.headers.get("content-type") || "application/octet-stream";
        const bytes = await res.arrayBuffer();
        const encrypted = await encryptFileBlob(key, bytes, contentType);
        const form = new FormData();
        form.append("file", encrypted, "encrypted");
        const uploaded = await api.uploadWithProgress<UploadResult>(`/uploads?space_id=${targetSpaceId}`, form);
        content = content.split(url).join(uploaded.url);
        const oldId = url.match(/\/api\/uploads\/([0-9a-f-]{36})/i)?.[1];
        if (oldId) oldUploadIds.push(oldId);
      }

      // 2. Шифруем итоговые title/content ключом ЦЕЛЕВОГО сейфа.
      const vault = { title: await encryptField(key, item.title), content: await encryptField(key, content) };

      // 3. Сохраняем зашифрованную версию, пока заметка ЕЩЁ в старом
      // спейсе (PATCH не проверяет is_vault — можно сохранить туда
      // properties.vault до move) — это и есть "доказательство шифрования",
      // которое move ниже потребует.
      await api.patch<Item>(`/items/${item.id}`, { title: VAULT_PLACEHOLDER, content: VAULT_PLACEHOLDER, vault });

      // 4. Сам перенос.
      const moved = await api.post<Item>(`/items/${item.id}/move`, { space_id: targetSpaceId });

      // 5. Чистим исходники — best-effort, не блокируем успех переноса,
      // если что-то из старых файлов уже недоступно.
      await Promise.all(oldUploadIds.map((id) => api.delete<void>(`/uploads/${id}`).catch(() => {})));

      return moved;
    },
    onSuccess: (item) => {
      qc.setQueryData(["item", item.id], item);
      qc.invalidateQueries({ queryKey: ["items"] });
    },
  });
}

// Смена пароля сейфа — двухфазная (см. VaultRotatePasswordIn на бэкенде):
// сначала перешифровываем и стейджим файлы (PUT .../staged, идемпотентно,
// можно повторить безопасно), потом ОДНИМ атомарным вызовом фиксируем
// новую соль/verifier + все заметки сразу. Если что-то упадёт ДО этого
// последнего вызова — старый пароль остаётся рабочим, ничего не потеряно.
export function useRotateVaultPassword() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({
      spaceId,
      oldKey,
      newPassword,
    }: {
      spaceId: string;
      oldKey: CryptoKey;
      newPassword: string;
    }) => {
      const newSalt = generateSalt();
      const newKey = await deriveKey(newPassword, newSalt);
      const newVerifier = await createVerifier(newKey);

      const items = await api.get<Item[]>(`/items?space_id=${spaceId}`);
      const decrypted = await Promise.all(
        items
          .filter((item) => item.vault)
          .map(async (item) => ({
            id: item.id,
            title: item.vault!.title ? await decryptField(oldKey, item.vault!.title) : item.title,
            content: item.vault!.content ? await decryptField(oldKey, item.vault!.content) : item.content,
          })),
      );

      // Уникальные id вложенных файлов по всем расшифрованным заметкам —
      // один и тот же файл может быть в нескольких, перешифровываем один раз.
      const uploadIds = new Set<string>();
      for (const d of decrypted) {
        for (const url of d.content.match(UPLOAD_URL_RE) ?? []) {
          const id = url.match(/[0-9a-f-]{36}/i)?.[0];
          if (id) uploadIds.add(id);
        }
      }
      for (const id of uploadIds) {
        const res = await fetch(`/api/uploads/${id}`, { credentials: "include" });
        if (!res.ok) continue;
        const contentType = res.headers.get("content-type") || "application/octet-stream";
        const rawBytes = await decryptFileBytes(oldKey, await res.arrayBuffer());
        const reencrypted = await encryptFileBlob(newKey, rawBytes, contentType);
        const form = new FormData();
        form.append("file", reencrypted, "encrypted");
        const staged = await fetch(`/api/uploads/${id}/staged`, {
          method: "PUT",
          credentials: "include",
          body: form,
        });
        if (!staged.ok) throw new Error(`Не удалось перешифровать файл ${id}`);
      }

      // content не переписывается — файлы заменяются на месте, id те же.
      const newItems = await Promise.all(
        decrypted.map(async (d) => ({
          id: d.id,
          vault: { title: await encryptField(newKey, d.title), content: await encryptField(newKey, d.content) },
        })),
      );

      await api.post(`/spaces/${spaceId}/vault-rotate-password`, {
        new_salt: newSalt,
        // Как и vault_verifier при создании сейфа (CreateSpaceButton.tsx) —
        // сервер хранит его строкой (schemas/space.py), а не структурой.
        new_verifier: JSON.stringify(newVerifier),
        items: newItems,
        upload_ids: Array.from(uploadIds),
      });

      unlockVault(spaceId, newKey);
    },
    onSuccess: (_result, vars) => {
      qc.invalidateQueries({ queryKey: ["items", vars.spaceId] });
      qc.invalidateQueries({ queryKey: ["item"] });
      // staleTime: Infinity у useVaultUnlockInfo — без явной инвалидации
      // старые соль/verifier остались бы в кэше и следующая попытка
      // разблокировки (например, после перезагрузки страницы) сверяла бы
      // новый пароль со старым verifier.
      qc.invalidateQueries({ queryKey: ["vault-unlock-info", vars.spaceId] });
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
    mutationFn: (payload?: { scoped_item_id?: string; selection?: string }) => api.post<Dialog>("/dialogs", payload ?? {}),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["dialogs"] }),
  });
}

// Все скретч-диалоги "Спросить ассистента" для конкретной заметки, новые
// сверху — NoteAssistantModal.tsx при открытии показывает их списком.
// Мутация, не query: нужен разовый императивный вызов в конкретный момент
// (при открытии панели), не закешированный автообновляющийся запрос.
export function useScopedDialogs() {
  return useMutation({
    mutationFn: (itemId: string) => api.get<DialogSummary[]>(`/dialogs/scoped/${itemId}`),
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

export function useAddMemory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (content: string) => api.post<AssistantMemoryFact>("/memories", { content }),
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
      const key = spaceId ? getVaultKey(spaceId) : undefined;
      const form = new FormData();
      if (!key) {
        form.append("file", file);
      } else {
        // Байты и имя шифруются на клиенте (ТЗ §16.2) — сервер получает
        // непрозрачный блоб под родовым именем ("encrypted", как и задаёт
        // сам Blob ниже) и настоящий MIME-тип файла (не секрет сам по
        // себе, в отличие от имени — "паспорт_скан.jpg" уже утечка, а
        // "image/jpeg" — нет), чтобы существующая раздача (Content-Type,
        // inline/attachment) продолжала работать не задумываясь о сейфе.
        const bytes = await file.arrayBuffer();
        const encrypted = await encryptFileBlob(key, bytes, file.type || "application/octet-stream");
        form.append("file", encrypted, "encrypted");
      }
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

// Кнопка «Обновить» на виджете «Проверить по ссылке» (UrlCheckCard.tsx) —
// прямой REST, без участия ассистента (тот нужен только один раз, при
// создании блока, tools/url_check.py::insert_url_check_block).
export function useCheckUrl() {
  return useMutation({
    mutationFn: (url: string) => api.post<UrlCheckFetchResult>("/url-checks/fetch", { url }),
  });
}

// Синхронный вариант распознавания картинки — для вложения в сообщение
// ассистенту (AssistantChat.tsx): результат нужен ДО отправки сообщения,
// не фоновой заменой плейсхолдера, как у вложений в заметку.
export function useDescribeUploadNow() {
  return useMutation({
    mutationFn: (uploadId: string) => api.post<{ description: string }>(`/uploads/${uploadId}/describe-now`),
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
    // Раньше раз в минуту был единственным способом узнать о наступившем
    // напоминании — теперь диспетчер (notification_dispatch.py) толкает
    // сигнал через WS (useNotificationSync) в пределах ~20с сам; опрос —
    // редкий fallback на случай разрыва соединения, не основной путь.
    refetchInterval: 5 * 60 * 1000,
  });
}

// scope=all — для ActivityView (см. ниже): в отличие от useNotifications
// (колокольчик, только due) включает ещё не наступившие напоминания.
// Отдельный queryKey — иначе инвалидация одного списка сбрасывала бы кэш
// другого без реальной необходимости перезапросить именно его.
export function useAllNotifications() {
  return useQuery<Notification[]>({
    queryKey: ["notifications", "all"],
    queryFn: () => api.get<Notification[]>("/notifications?scope=all"),
  });
}

export function useDeleteNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete(`/notifications/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

// "Выполнено" — независимо от trigger_at (см. ActivityView.tsx): резолв
// не значит "прошло время", значит "пользователь сам отметил".
export function useResolveNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Notification>(`/notifications/${id}/resolve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

export function useUnresolveNotification() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Notification>(`/notifications/${id}/unresolve`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
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

export function useCreateReminder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { title: string; body?: string; trigger_at: string; item_id?: string }) =>
      api.post<Notification>("/notifications", payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}

// --- link preview --------------------------------------------------------

// Кэш на бэкенде бессрочный (см. routers/link_preview.py), поэтому и здесь
// не нужно перезапрашивать при каждом фокусе — карточка сайта не меняется.
export function useLinkPreview(url: string | undefined) {
  return useQuery<LinkPreviewData>({
    queryKey: ["link-preview", url],
    queryFn: () => api.get<LinkPreviewData>(`/link-preview?url=${encodeURIComponent(url!)}`),
    enabled: !!url,
    staleTime: Infinity,
    retry: false,
  });
}

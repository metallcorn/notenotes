// Мелкое состояние UI (что свёрнуто, что открыто последним) — не часть
// данных на бэкенде, живёт только в браузере. localStorage, а не react-query
// cache: должно переживать перезагрузку страницы.

const PREFIX = "notenotes:";

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    return raw !== null ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // приватный режим / квота исчерпана — не критично, просто не запомнили
  }
}

export interface ActiveSelection {
  spaceId: string;
  folderId: string | null;
}

export const uiStorage = {
  getLastItemId: (spaceId: string): string | null => read<string | null>(`lastItem:${spaceId}`, null),
  setLastItemId: (spaceId: string, itemId: string | null): void => write(`lastItem:${spaceId}`, itemId),

  getCollapsedSpaces: (): string[] => read<string[]>("collapsedSpaces", []),
  setCollapsedSpaces: (ids: string[]): void => write("collapsedSpaces", ids),

  getSidebarCollapsed: (): boolean => read<boolean>("sidebarCollapsed", false),
  setSidebarCollapsed: (v: boolean): void => write("sidebarCollapsed", v),

  getListCollapsed: (): boolean => read<boolean>("listCollapsed", false),
  setListCollapsed: (v: boolean): void => write("listCollapsed", v),

  getActiveSelection: (): ActiveSelection | null => read<ActiveSelection | null>("activeSelection", null),
  setActiveSelection: (v: ActiveSelection | null): void => write("activeSelection", v),

  // Отдельно от activeSelection: тот пишется только из выбора папки в
  // Заметках (selectFolder) — если последним пользователь сидел в
  // Ассистенте, activeSelection.spaceId мог быть про другой (старый)
  // спейс. При рестарте это резолвило дефолтный спейс не туда, и список
  // диалогов ассистента выглядел пустым — "куда-то пропали чаты"
  // (реальная жалоба). lastSpaceId пишется при КАЖДОЙ смене активного
  // спейса, независимо от экрана (заметки/ассистент/корзина).
  getLastSpaceId: (): string | null => read<string | null>("lastSpaceId", null),
  setLastSpaceId: (v: string | null): void => write("lastSpaceId", v),

  // Ширина текста в редакторе — как в Confluence: узкий/широкий/во весь
  // экран. Глобальная настройка чтения, не свойство конкретной заметки.
  getContentWidth: (): ContentWidth => read<ContentWidth>("contentWidth", "narrow"),
  setContentWidth: (v: ContentWidth): void => write("contentWidth", v),

  // Тот же переключатель ширины, что у заметок, но отдельная настройка —
  // ширина чата с ассистентом не обязана совпадать с шириной заметок.
  getChatContentWidth: (): ContentWidth => read<ContentWidth>("chatContentWidth", "narrow"),
  setChatContentWidth: (v: ContentWidth): void => write("chatContentWidth", v),

  // Какой из трёх верхнеуровневых экранов был открыт — иначе обновление
  // страницы всегда откатывало на «Заметки», даже если человек сидел в
  // Ассистенте или Корзине (жалоба из отзыва).
  getViewMode: (): ViewMode => read<ViewMode>("viewMode", "notes"),
  setViewMode: (v: ViewMode): void => write("viewMode", v),

  getLastDialogId: (spaceId: string): string | null => read<string | null>(`lastDialog:${spaceId}`, null),
  setLastDialogId: (spaceId: string, dialogId: string | null): void => write(`lastDialog:${spaceId}`, dialogId),

  // Автоозвучивание новых ответов ассистента (TTS) — глобальный переключатель,
  // отдельный от ручной кнопки "озвучить" на каждой реплике.
  getAutoSpeak: (): boolean => read<boolean>("autoSpeak", false),
  setAutoSpeak: (v: boolean): void => write("autoSpeak", v),
};

export type ContentWidth = "narrow" | "wide" | "full";
export type ViewMode = "notes" | "assistant" | "trash";

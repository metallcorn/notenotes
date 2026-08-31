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

  // Ширина панели спейсов/списка заметок на десктопе (px, перетаскиванием
  // за границу панели) — реальная жалоба: раньше была фиксированной
  // (256/320px), тот же принцип, что и у getNotePanelWidth.
  getSidebarWidth: (): number => read<number>("sidebarWidth", 256),
  setSidebarWidth: (v: number): void => write("sidebarWidth", v),

  getListPanelWidth: (): number => read<number>("listPanelWidth", 320),
  setListPanelWidth: (v: number): void => write("listPanelWidth", v),

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

  // Ширина боковой панели "Спросить ассистента" на десктопе (px,
  // перетаскиванием) — реальная жалоба: фиксированные 420px не подходят
  // всем, хочется двигать самому, как и остальные ширины в приложении.
  getNotePanelWidth: (): number => read<number>("notePanelWidth", 420),
  setNotePanelWidth: (v: number): void => write("notePanelWidth", v),

  // Какой из трёх верхнеуровневых экранов был открыт — иначе обновление
  // страницы всегда откатывало на «Заметки», даже если человек сидел в
  // Ассистенте или Корзине (жалоба из отзыва).
  getViewMode: (): ViewMode => read<ViewMode>("viewMode", "notes"),
  setViewMode: (v: ViewMode): void => write("viewMode", v),

  // Один глобальный ключ, не по спейсам — диалоги ассистента больше не
  // привязаны к спейсу с точки зрения пользователя (список общий на все
  // спейсы сразу), так что и "последний открытый диалог" тоже один на всё,
  // а не разный для каждого спейса.
  getLastDialogId: (): string | null => read<string | null>("lastDialog", null),
  setLastDialogId: (dialogId: string | null): void => write("lastDialog", dialogId),

  // Автоозвучивание новых ответов ассистента (TTS) — глобальный переключатель,
  // отдельный от ручной кнопки "озвучить" на каждой реплике.
  getAutoSpeak: (): boolean => read<boolean>("autoSpeak", false),
  setAutoSpeak: (v: boolean): void => write("autoSpeak", v),

  // Реальная жалоба: технические чипы вызовов инструментов (ToolCallRow —
  // "🔧 search_base" и т.п.) занимают место и выглядят некрасиво в обычном
  // использовании, но крайне полезны для отладки — не убираем совсем, а
  // прячем по умолчанию за переключателем в шапке чата.
  getShowToolDebug: (): boolean => read<boolean>("showToolDebug", false),
  setShowToolDebug: (v: boolean): void => write("showToolDebug", v),

  // Три режима заметки — Просмотр (только читать)/WYSIWYG/Markdown.
  // Реальная просьба: последний выбранный режим должен переживать переход
  // между заметками и перезагрузку — иначе каждая заметка открывается в
  // WYSIWYG заново, даже если человек специально держит "Просмотр", чтобы
  // листать заметки без риска что-то случайно поменять или вызвать
  // клавиатуру на мобильном.
  getNoteEditorMode: (): NoteEditorMode => read<NoteEditorMode>("noteEditorMode", "wysiwyg"),
  setNoteEditorMode: (v: NoteEditorMode): void => write("noteEditorMode", v),

  // Тёмная тема (KDE Breeze Dark) — "system" дефолтом: пользователь,
  // просивший эту фичу, сидит в тёмном KDE, "системная" сразу даёт ему
  // то, что нужно, без лишнего клика; кто угодно другой на светлой ОС
  // как видел светлую тему, так и продолжит её видеть. Читается СИНХРОННО
  // инлайн-скриптом в index.html до монтирования React (см. lib/theme.ts)
  // — без этого при загрузке страница на долю секунды мигала бы светлым.
  getTheme: (): Theme => read<Theme>("theme", "system"),
  setTheme: (v: Theme): void => write("theme", v),
};

export type ContentWidth = "narrow" | "wide" | "full";
export type ViewMode = "notes" | "assistant" | "trash" | "activity";
export type NoteEditorMode = "view" | "wysiwyg" | "raw";
export type Theme = "light" | "dark" | "system";

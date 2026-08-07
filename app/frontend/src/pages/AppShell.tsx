import { useEffect, useRef, useState } from "react";
import { ChevronLeft, Sparkles, Trash2 } from "lucide-react";
import { useSpaces } from "../api/hooks";
import { uiStorage, type ViewMode } from "../lib/storage";
import { withViewTransition } from "../lib/viewTransition";
import { useVersionCheck } from "../lib/useVersionCheck";
import { useSpaceSync } from "../lib/useSpaceSync";
import CreateSpaceButton from "../components/CreateSpaceButton";
import SpaceSection from "../components/SpaceSection";
import TagList from "../components/TagList";
import NoteList from "../components/NoteList";
import ItemView from "../components/ItemView";
import SearchBar from "../components/SearchBar";
import SearchResults from "../components/SearchResults";
import UserMenu from "../components/UserMenu";
import NotificationBell from "../components/NotificationBell";
import DialogList from "../components/DialogList";
import AssistantChat from "../components/AssistantChat";
import TrashView from "../components/TrashView";

type MobileView = "sidebar" | "list" | "editor";

export default function AppShell() {
  const { data: spaces } = useSpaces();
  const updateAvailable = useVersionCheck();

  const [activeSpaceId, setActiveSpaceId] = useState<string | undefined>(undefined);
  useSpaceSync(activeSpaceId);
  useEffect(() => {
    if (activeSpaceId) uiStorage.setLastSpaceId(activeSpaceId);
  }, [activeSpaceId]);
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
  const [tagId, setTagId] = useState<string | null>(null);
  const [selectedItemId, setSelectedItemIdState] = useState<string | null>(null);
  const [highlightEntryId, setHighlightEntryId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [viewMode, setViewModeState] = useState<ViewMode>(() => uiStorage.getViewMode());
  const [selectedDialogId, setSelectedDialogId] = useState<string | null>(null);

  // Отдельная от sidebarCollapsed/listCollapsed штука: те — десктопное
  // «схлопнуть в полоску», это — какая из трёх панелей показана на узком
  // экране, где все три рядом физически не помещаются (см. отзыв с
  // телефона — редактор просто уезжал за край экрана).
  const [mobileView, setMobileView] = useState<MobileView>("list");

  const [collapsedSpaces, setCollapsedSpaces] = useState<Set<string>>(() => new Set(uiStorage.getCollapsedSpaces()));
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => uiStorage.getSidebarCollapsed());
  const [listCollapsed, setListCollapsed] = useState(() => uiStorage.getListCollapsed());

  const restoredRef = useRef(false);

  // Восстановление состояния — один раз, при первой загрузке списка спейсов
  // (раньше некуда, useSpaces() ещё пуст на первом рендере), и только на
  // старте страницы, не при каждой смене activeSpaceId: иначе клик по папке
  // в спейсе, который в эту сессию открывают впервые, сразу перебивался бы
  // автовосстановлением последней заметки того спейса.
  //
  // Сохранённая папка и сохранённая «последняя открытая заметка» обновляются
  // по разным событиям и могут разойтись (кликнули в другую папку, ничего
  // там не открыв). Поэтому если восстанавливаем заметку — папку принудительно
  // ставим на «Все заметки», чтобы заметка гарантированно была видна в
  // списке, а не показывала пустую панель рядом с открытой заметкой.
  useEffect(() => {
    if (restoredRef.current || !spaces || spaces.length === 0) return;
    restoredRef.current = true;
    const saved = uiStorage.getActiveSelection();
    const valid = saved && spaces.some((s) => s.id === saved.spaceId) ? saved : null;
    // lastSpaceId — приоритетнее activeSelection: тот пишется только из
    // выбора папки в Заметках, а lastSpaceId — из любого экрана, включая
    // Ассистента (см. комментарий в storage.ts).
    const lastSpaceId = uiStorage.getLastSpaceId();
    const validLastSpaceId = lastSpaceId && spaces.some((s) => s.id === lastSpaceId) ? lastSpaceId : null;
    const spaceId = validLastSpaceId ?? valid?.spaceId ?? spaces[0].id;
    setActiveSpaceId(spaceId);

    // Экран (заметки/ассистент/корзина) — отдельная ось от папки/заметки:
    // без этого обновление страницы всегда откатывало на «Заметки», даже
    // если сидели в Ассистенте или Корзине.
    const savedViewMode = uiStorage.getViewMode();
    if (savedViewMode === "assistant") {
      setViewModeState("assistant");
      const lastDialogId = uiStorage.getLastDialogId(spaceId);
      if (lastDialogId) {
        setSelectedDialogId(lastDialogId);
        setMobileView("editor");
      } else {
        setMobileView("list");
      }
      return;
    }
    if (savedViewMode === "trash") {
      setViewModeState("trash");
      setMobileView("list");
      return;
    }

    const lastItemId = uiStorage.getLastItemId(spaceId);
    if (lastItemId) {
      setActiveFolderId(null);
      setSelectedItemIdState(lastItemId);
      setMobileView("editor");
    } else {
      setActiveFolderId(valid?.folderId ?? null);
    }
  }, [spaces]);

  function setViewMode(mode: ViewMode) {
    setViewModeState(mode);
    uiStorage.setViewMode(mode);
  }

  function setSelectedItemId(id: string | null) {
    withViewTransition(() => {
      setSelectedItemIdState(id);
      setMobileView(id ? "editor" : "list");
    });
    if (activeSpaceId) uiStorage.setLastItemId(activeSpaceId, id);
  }

  function selectFolder(spaceId: string, folderId: string | null) {
    setViewMode("notes");
    setActiveSpaceId(spaceId);
    setActiveFolderId(folderId);
    setTagId(null);
    setSelectedItemId(null);
    uiStorage.setActiveSelection({ spaceId, folderId });
  }

  function openReminder(spaceId: string, itemId: string, entryId?: string) {
    setViewMode("notes");
    setActiveSpaceId(spaceId);
    setActiveFolderId(null);
    setTagId(null);
    setHighlightEntryId(entryId ?? null);
    setSelectedItemId(itemId);
  }

  function selectTag(id: string | null) {
    setViewMode("notes");
    setTagId(id);
    setSelectedItemId(null);
    withViewTransition(() => setMobileView("list"));
  }

  function switchToAssistant() {
    withViewTransition(() => {
      setViewMode("assistant");
      setMobileView("list");
    });
  }

  function switchToTrash() {
    withViewTransition(() => {
      setViewMode("trash");
      setMobileView("list");
    });
  }

  function selectDialog(id: string | null) {
    withViewTransition(() => {
      setSelectedDialogId(id);
      setMobileView(id ? "editor" : "list");
    });
    if (activeSpaceId) uiStorage.setLastDialogId(activeSpaceId, id);
  }

  function toggleSpaceCollapsed(spaceId: string) {
    withViewTransition(() => {
      setCollapsedSpaces((prev) => {
        const next = new Set(prev);
        if (next.has(spaceId)) next.delete(spaceId);
        else next.add(spaceId);
        uiStorage.setCollapsedSpaces(Array.from(next));
        return next;
      });
    });
  }

  function toggleSidebar() {
    withViewTransition(() => {
      setSidebarCollapsed((v) => {
        const next = !v;
        uiStorage.setSidebarCollapsed(next);
        return next;
      });
    });
  }

  function toggleList() {
    withViewTransition(() => {
      setListCollapsed((v) => {
        const next = !v;
        uiStorage.setListCollapsed(next);
        return next;
      });
    });
  }

  return (
    <div className="flex h-dvh bg-white text-slate-900">
      <aside
        className={`${mobileView === "sidebar" ? "flex" : "hidden"} ${
          sidebarCollapsed ? "lg:hidden" : "lg:flex"
        } w-full shrink-0 flex-col border-r bg-slate-50 lg:w-64`}
      >
        {/* На десктопе строка поиска уже есть в панели списка заметок,
            видна одновременно с сайдбаром. На мобиле экраны сменяют друг
            друга по одному — без этого поиск был доступен только после
            захода в конкретную папку, не с главного экрана (жалоба). */}
        <div className="border-b p-3 lg:hidden">
          <SearchBar
            value={query}
            onChange={(v) => {
              setQuery(v);
              if (v.trim()) {
                setViewMode("notes");
                withViewTransition(() => setMobileView("list"));
              }
            }}
          />
        </div>
        {/* Скроллится только список спейсов/папок/тегов — футер профиля
            нарочно СНАРУЖИ этого div: иначе overflow-y-auto родителя
            обрезает всплывающие окна UserMenu/NotificationBell, у которых
            containing block лежит внутри скролл-контейнера (классический
            CSS-баг с overflow, который "перекрывает интерфейсом" попапы). */}
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          <div className="mb-3 space-y-0.5">
            <button
              onClick={switchToAssistant}
              className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm ${
                viewMode === "assistant" ? "bg-slate-200 font-medium text-slate-900" : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              <Sparkles size={15} /> Ассистент
            </button>
            <button
              onClick={switchToTrash}
              className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm ${
                viewMode === "trash" ? "bg-slate-200 font-medium text-slate-900" : "text-slate-600 hover:bg-slate-100"
              }`}
            >
              <Trash2 size={15} /> Корзина
            </button>
          </div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-400">Спейсы</span>
            <CreateSpaceButton onCreated={(id) => selectFolder(id, null)} />
          </div>
          {(spaces ?? []).map((space) => (
            <SpaceSection
              key={space.id}
              space={space}
              isActive={activeSpaceId === space.id}
              activeFolderId={activeFolderId}
              collapsed={collapsedSpaces.has(space.id)}
              onToggleCollapse={() => toggleSpaceCollapsed(space.id)}
              onSelectFolder={selectFolder}
            />
          ))}
          <TagList selectedTagId={tagId} onSelect={selectTag} />
        </div>
        <div className="flex shrink-0 items-center gap-1 border-t p-3">
          <UserMenu />
          <NotificationBell updateAvailable={updateAvailable} onOpenReminder={openReminder} />
        </div>
      </aside>

      <button
        onClick={toggleSidebar}
        title={sidebarCollapsed ? "Показать панель" : "Скрыть панель"}
        className="hidden w-4 shrink-0 items-center justify-center border-r bg-slate-50 text-slate-400 hover:bg-slate-100 lg:flex"
      >
        {sidebarCollapsed ? "›" : "‹"}
      </button>

      <main className="flex min-h-0 flex-1 overflow-hidden">
        {viewMode === "trash" ? (
          <TrashView spaceId={activeSpaceId} onBack={() => withViewTransition(() => setMobileView("sidebar"))} />
        ) : (
          <>
            <div
              className={`${mobileView === "list" ? "flex" : "hidden"} ${
                listCollapsed ? "lg:hidden" : "lg:flex"
              } w-full shrink-0 flex-col border-r lg:w-80`}
            >
              {viewMode === "notes" ? (
                <>
                  <div className="flex items-center gap-1 border-b p-3">
                    <button
                      onClick={() => withViewTransition(() => setMobileView("sidebar"))}
                      className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 lg:hidden"
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <SearchBar value={query} onChange={setQuery} />
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto">
                    {query.trim() ? (
                      <SearchResults query={query} selectedId={selectedItemId} onSelect={setSelectedItemId} />
                    ) : activeSpaceId ? (
                      <NoteList
                        spaceId={activeSpaceId}
                        folderId={activeFolderId}
                        tagId={tagId}
                        selectedId={selectedItemId}
                        onSelect={setSelectedItemId}
                      />
                    ) : (
                      <div className="p-3 text-sm text-slate-400">Нет доступных спейсов</div>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className="flex items-center gap-1 border-b p-3 lg:hidden">
                    <button
                      onClick={() => withViewTransition(() => setMobileView("sidebar"))}
                      className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500"
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <span className="text-sm font-medium text-slate-900">Ассистент</span>
                  </div>
                  <DialogList spaceId={activeSpaceId} selectedId={selectedDialogId} onSelect={selectDialog} />
                </>
              )}
            </div>

            <button
              onClick={toggleList}
              title={listCollapsed ? "Показать список" : "Скрыть список"}
              className="hidden w-4 shrink-0 items-center justify-center border-r bg-white text-slate-300 hover:bg-slate-50 lg:flex"
            >
              {listCollapsed ? "›" : "‹"}
            </button>

            <div className={`${mobileView === "editor" ? "flex" : "hidden"} lg:flex min-h-0 flex-1 flex-col overflow-hidden`}>
              {viewMode === "notes" ? (
                selectedItemId ? (
                  <ItemView
                    itemId={selectedItemId}
                    onDeleted={() => setSelectedItemId(null)}
                    onBack={() => withViewTransition(() => setMobileView("list"))}
                    highlightEntryId={highlightEntryId}
                  />
                ) : (
                  <div className="flex h-full items-center justify-center text-slate-400">
                    Выберите заметку слева или создайте новую
                  </div>
                )
              ) : selectedDialogId ? (
                <AssistantChat
                  dialogId={selectedDialogId}
                  onBack={() => withViewTransition(() => setMobileView("list"))}
                  onOpenItem={(id) => {
                    setViewMode("notes");
                    setActiveFolderId(null);
                    setTagId(null);
                    setSelectedItemId(id);
                  }}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-slate-400">
                  Выберите диалог слева или создайте новый
                </div>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ChevronLeft, Sparkles, Trash2 } from "lucide-react";
import { useSpaces } from "../api/hooks";
import { uiStorage, type ViewMode } from "../lib/storage";
import { withViewTransition } from "../lib/viewTransition";
import { useVersionCheck } from "../lib/useVersionCheck";
import { useSpaceSync } from "../lib/useSpaceSync";
import { useNotificationSync } from "../lib/useNotificationSync";
import { diagnosticLog } from "../lib/diagnostics";
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
  // URL — источник истины для того, какая заметка/диалог открыты (не
  // только React state): без этого системный жест «назад» на телефоне не
  // находит в history этого приложения ничего своего и закрывает всё
  // приложение целиком, а обновление страницы после ухода «назад» кнопкой
  // интерфейса снова открывало ту же заметку — оба симптома одной причины
  // (реальная жалоба). react-router-dom уже используется в проекте
  // (App.tsx, login/register), новая зависимость не нужна.
  const [searchParams, setSearchParams] = useSearchParams();

  const [activeSpaceId, setActiveSpaceId] = useState<string | undefined>(undefined);
  useSpaceSync(activeSpaceId);
  useNotificationSync();
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
  // Точечная диагностика бага "белый экран в standalone PWA при переходе
  // список → sidebar" (см. diagnostics.ts) — ref на корневой div ниже,
  // чтобы читать его реальную геометрию в момент перехода и чуть позже.
  const rootRef = useRef<HTMLDivElement>(null);

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
    if (!spaces || spaces.length === 0) return;
    const saved = uiStorage.getActiveSelection();
    const valid = saved && spaces.some((s) => s.id === saved.spaceId) ? saved : null;
    // lastSpaceId — приоритетнее activeSelection: тот пишется только из
    // выбора папки в Заметках, а lastSpaceId — из любого экрана, включая
    // Ассистента (см. комментарий в storage.ts).
    const lastSpaceId = uiStorage.getLastSpaceId();
    const validLastSpaceId = lastSpaceId && spaces.some((s) => s.id === lastSpaceId) ? lastSpaceId : null;
    const spaceId = validLastSpaceId ?? valid?.spaceId ?? spaces[0].id;
    // activeSpaceId нужен на каждом входе в этот эффект (в т.ч. на каждом
    // обновлении страницы) — иначе сайдбар и useSpaceSync остались бы без
    // спейса после первого же reload, если восстановление URL ниже
    // пропущено sessionStorage-гардом.
    setActiveSpaceId(spaceId);

    if (restoredRef.current) return;
    restoredRef.current = true;
    // sessionStorage, не только restoredRef — тот сбрасывается на каждом
    // обновлении страницы (React перемонтируется заново), а sessionStorage
    // переживает reload той же вкладки. Без этого уход на sidebar кнопкой
    // «назад» (bare "/", без ?list=1) и последующее обновление страницы
    // заново подставляли бы «последнее место» из localStorage поверх
    // явного текущего состояния URL — тот же баг, что уже чинили для
    // заметок, теперь на уровне sidebar (реальная жалоба). Восстановление
    // URL (ниже) должно случиться только один раз за сессию вкладки —
    // activeSpaceId выше от этого не зависит и выставляется всегда.
    if (sessionStorage.getItem("notenotes-restored")) return;
    sessionStorage.setItem("notenotes-restored", "1");

    // В URL уже указана заметка/диалог (прямая ссылка, PWA-ярлык) —
    // приоритет у неё, восстановление из localStorage ниже не нужно:
    // эффект-синхронизация (см. ниже) сам разберёт URL. viewMode всё
    // равно нужно выставить, чтобы открылся правильный экран.
    if (searchParams.get("dialog")) {
      setViewModeState("assistant");
      return;
    }
    if (searchParams.get("item")) {
      return;
    }

    // Всегда сначала replace на чистый корень — это база стека (экран
    // "sidebar"), а следующий шаг push кладёт список поверх неё. Без
    // этого при обычном холодном открытии приложения (сразу список
    // заметок, без явного клика по папке) в history не было НИ ОДНОЙ
    // записи — системный жест «назад» первым же нажатием закрывал всё
    // приложение целиком, а не показывал sidebar (реальная жалоба).
    setSearchParams(new URLSearchParams(), { replace: true });

    // Экран (заметки/ассистент/корзина) — отдельная ось от папки/заметки:
    // без этого обновление страницы всегда откатывало на «Заметки», даже
    // если сидели в Ассистенте или Корзине.
    const savedViewMode = uiStorage.getViewMode();
    if (savedViewMode === "assistant") {
      setViewModeState("assistant");
      const lastDialogId = uiStorage.getLastDialogId();
      setSearchParams(lastDialogId ? { dialog: lastDialogId, list: "1" } : { list: "1" });
      return;
    }
    if (savedViewMode === "trash") {
      setViewModeState("trash");
      setSearchParams({ list: "1" });
      return;
    }

    const lastItemId = uiStorage.getLastItemId(spaceId);
    if (lastItemId) {
      setActiveFolderId(null);
      setSearchParams({ item: lastItemId, list: "1" });
    } else {
      setActiveFolderId(valid?.folderId ?? null);
      setSearchParams({ list: "1" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spaces]);

  // Единственное место, которое реально пишет в selectedItemId/
  // selectedDialogId — источник истины URL, не отдельные setState-вызовы.
  // Срабатывает и на программное открытие (setSelectedItemId/selectDialog
  // ниже), и на popstate от кнопки браузера/системного жеста «назад» —
  // это ровно то же самое событие для React, что и обычный переход по
  // ссылке, отдельно ловить popstate не нужно.
  useEffect(() => {
    const itemParam = searchParams.get("item");
    const dialogParam = searchParams.get("dialog");
    const listParam = searchParams.get("list");
    const nextMobileView = itemParam || dialogParam ? "editor" : listParam ? "list" : "sidebar";
    diagnosticLog("search_params_sync_start", {
      nextMobileView,
      rootRect: rootRef.current?.getBoundingClientRect().toJSON() ?? null,
    });
    withViewTransition(() => {
      setSelectedItemIdState(itemParam);
      setSelectedDialogId(dialogParam);
      setMobileView(nextMobileView);
    });
    if (activeSpaceId) uiStorage.setLastItemId(activeSpaceId, itemParam);
    uiStorage.setLastDialogId(dialogParam);
    // Геометрия ПОСЛЕ перерисовки — сравнить с rootRect выше: если экран
    // белый именно из-за схлопнувшейся высоты (гипотеза про dvh в Firefox
    // Android), тут будет видно нулевую/аномальную высоту.
    setTimeout(() => {
      diagnosticLog("search_params_sync_settled", {
        nextMobileView,
        rootRect: rootRef.current?.getBoundingClientRect().toJSON() ?? null,
      });
    }, 300);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function setViewMode(mode: ViewMode) {
    setViewModeState(mode);
    uiStorage.setViewMode(mode);
  }

  function setSelectedItemId(id: string | null, options?: { forcePush?: boolean }) {
    // Тот же принцип, что в openListView: уже открыта заметка (десктоп,
    // клик по другой заметке в списке прямо из открытого редактора,
    // обычный рабочий процесс) — replace, а не push, иначе каждый такой
    // клик копит в history отдельную запись и «назад» приходится жать
    // отдельно на каждую просмотренную заметку, а не один раз к списку.
    // forcePush — исключение из этого правила: переход НЕ между заметками,
    // а «нырок» из другого контекста (диалог с ассистентом → заметка по
    // ссылке из ответа, уведомление → заметка) — тут реплейс стирал бы из
    // истории тот самый диалог/экран, откуда пришли, и «назад» уводил бы
    // мимо него (жалоба в отзыве: «думал что вернусь туда, где реально был»).
    const alreadyOnEditor = mobileView === "editor" && !options?.forcePush;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) {
          // list=1 остаётся вместе с item: closeItemView ниже трогает
          // только item/dialog, чтобы «назад» из заметки приземлялся на
          // список, а не сразу перепрыгивал через него на sidebar.
          next.set("item", id);
          next.set("list", "1");
          next.delete("dialog");
        } else {
          next.delete("item");
        }
        return next;
      },
      alreadyOnEditor ? { replace: true } : undefined,
    );
  }

  // Кнопка «назад» в интерфейсе — прямой сброс (replace, не push): не
  // полагается на то, что в history вообще есть куда возвращаться (если
  // на заметку зашли по прямой ссылке, а не через переход внутри
  // приложения, navigate(-1) увёл бы из приложения совсем). Системный
  // жест «назад» на телефоне работает независимо и уже сам корректно
  // возвращается на предыдущую запись в history — ту, что появилась в
  // момент открытия заметки (обычный push в setSelectedItemId выше).
  function closeItemView() {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("item");
      next.delete("dialog");
      return next;
    }, { replace: true });
  }

  // Переход на экран списка — push, только если реально спускаемся на
  // уровень глубже (с sidebar или из редактора); если уже на списке и
  // просто переключаем папку/тег/раздел — replace. Раньше пушило всегда,
  // и клики по папкам ВНУТРИ списка (папка/тег сами по себе не часть
  // URL — activeFolderId/tagId это React state) копили в history кучу
  // неотличимых на вид записей "?list=1" подряд — жест «назад» после
  // сессии с несколькими переключениями папок должен был пройти через
  // ВСЕ них по одной, прежде чем реально попасть на sidebar, и выглядело
  // это как "назад вообще ничего не делает" (реальная жалоба).
  function openListView() {
    const alreadyOnList = mobileView === "list";
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("item");
        next.delete("dialog");
        next.set("list", "1");
        return next;
      },
      alreadyOnList ? { replace: true } : undefined,
    );
  }

  // Кнопка «назад к списку спейсов» — тот же принцип, что closeItemView:
  // прямой replace, не полагается на глубину history.
  function closeListView() {
    diagnosticLog("close_list_view_clicked", {
      mobileView,
      rootRect: rootRef.current?.getBoundingClientRect().toJSON() ?? null,
    });
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("item");
      next.delete("dialog");
      next.delete("list");
      return next;
    }, { replace: true });
  }

  function selectFolder(spaceId: string, folderId: string | null) {
    setViewMode("notes");
    setActiveSpaceId(spaceId);
    setActiveFolderId(folderId);
    setTagId(null);
    openListView();
    uiStorage.setActiveSelection({ spaceId, folderId });
  }

  function openReminder(spaceId: string, itemId: string, entryId?: string) {
    setViewMode("notes");
    setActiveSpaceId(spaceId);
    setActiveFolderId(null);
    setTagId(null);
    setHighlightEntryId(entryId ?? null);
    setSelectedItemId(itemId, { forcePush: true });
  }

  function selectTag(id: string | null) {
    setViewMode("notes");
    setTagId(id);
    openListView();
  }

  function switchToAssistant() {
    setViewMode("assistant");
    openListView();
  }

  function switchToTrash() {
    setViewMode("trash");
    openListView();
  }

  function selectDialog(id: string | null) {
    // Тот же принцип, что в setSelectedItemId/openListView.
    const alreadyOnEditor = mobileView === "editor";
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) {
          next.set("dialog", id);
          next.set("list", "1");
          next.delete("item");
        } else {
          next.delete("dialog");
        }
        return next;
      },
      alreadyOnEditor ? { replace: true } : undefined,
    );
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
    <div
      ref={rootRef}
      className="flex h-dvh bg-white text-slate-900"
      style={{
        boxSizing: "border-box",
        paddingTop: "var(--safe-top)",
        paddingRight: "var(--safe-right)",
        paddingBottom: "var(--safe-bottom)",
        paddingLeft: "var(--safe-left)",
      }}
    >
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
                openListView();
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
          <TrashView spaceId={activeSpaceId} onBack={closeListView} />
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
                      onClick={closeListView}
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
                      onClick={closeListView}
                      className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500"
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <span className="text-sm font-medium text-slate-900">Ассистент</span>
                  </div>
                  <DialogList selectedId={selectedDialogId} onSelect={selectDialog} />
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
                    onDeleted={closeItemView}
                    onBack={closeItemView}
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
                  onBack={closeItemView}
                  onOpenItem={(id) => {
                    setViewMode("notes");
                    setActiveFolderId(null);
                    setTagId(null);
                    setSelectedItemId(id, { forcePush: true });
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

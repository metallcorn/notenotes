import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bell, ChevronLeft, ChevronRight, FileStack, Sparkles, Trash2 } from "lucide-react";
import { useSpaces } from "../api/hooks";
import { uiStorage, type ViewMode } from "../lib/storage";
import { withViewTransition } from "../lib/viewTransition";
import { useResizeHandle } from "../lib/useResizablePanel";
import { useVersionCheck } from "../lib/useVersionCheck";
import { useSpaceSync } from "../lib/useSpaceSync";
import { useNotificationSync } from "../lib/useNotificationSync";
import CreateSpaceButton from "../components/CreateSpaceButton";
import SpaceSection from "../components/SpaceSection";
import TagList from "../components/TagList";
import NoteList from "../components/NoteList";
import VaultUnlockOverlay from "../components/VaultUnlockOverlay";
import { useVaultUnlocked } from "../lib/vaultSession";
import ItemView from "../components/ItemView";
import SearchBar from "../components/SearchBar";
import SearchResults from "../components/SearchResults";
import UserMenu from "../components/UserMenu";
import NotificationBell from "../components/NotificationBell";
import DialogList from "../components/DialogList";
import AssistantChat from "../components/AssistantChat";
import TrashView from "../components/TrashView";
import ActivityView from "../components/ActivityView";
import DocumentsView from "../components/DocumentsView";
import OfflineBanner from "../components/OfflineBanner";
import OfflineFlushNotice from "../components/OfflineFlushNotice";

type MobileView = "sidebar" | "list" | "editor";

// Порядок "глубины" мобильного стека — sidebar (корень) → list → editor.
// Реальная жалоба: переходы между экранами ощущались как обычный fade, а
// не слайд, свойственный навигации "вглубь"/"назад". View Transitions API
// сам по себе не знает направления — до вызова withViewTransition
// проставляем data-атрибут на <html>, index.css выбирает нужные keyframes
// по нему (см. комментарий там же).
const MOBILE_VIEW_DEPTH: Record<MobileView, number> = { sidebar: 0, list: 1, editor: 2 };

function setTransitionDirection(from: MobileView, to: MobileView): void {
  const dir = MOBILE_VIEW_DEPTH[to] >= MOBILE_VIEW_DEPTH[from] ? "forward" : "back";
  document.documentElement.setAttribute("data-transition-dir", dir);
}

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
  const activeSpace = spaces?.find((s) => s.id === activeSpaceId);
  // Реальный найденный баг (React error #311 — "calling Hooks
  // conditionally"): `!!x && !useVaultUnlocked(...)` — && коротко замыкает,
  // хук вызывается ТОЛЬКО когда x истинно. Количество вызванных хуков в
  // компоненте между рендерами менялось ровно в момент переключения
  // активного спейса на сейф/с сейфа — краш всего дерева. Хук должен
  // вызываться безусловно на каждый рендер, финальный булев результат —
  // уже отдельным выражением.
  const activeVaultUnlocked = useVaultUnlocked(activeSpace?.is_vault ? activeSpaceId : undefined);
  const activeVaultLocked = !!activeSpace?.is_vault && !activeVaultUnlocked;
  useEffect(() => {
    if (activeSpaceId) uiStorage.setLastSpaceId(activeSpaceId);
  }, [activeSpaceId]);
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
  const [tagId, setTagId] = useState<string | null>(null);
  const [selectedItemId, setSelectedItemIdState] = useState<string | null>(null);
  const [highlightEntryId, setHighlightEntryId] = useState<string | null>(null);
  const [highlightAnchorId, setHighlightAnchorId] = useState<string | null>(null);
  // Сам параметр читается из URL (см. setSelectedItemId) — отдельного
  // состояния нет намеренно, иначе оно расходится с адресом.
  const findText = searchParams.get("find");
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
  const [sidebarWidth, setSidebarWidth] = useState(() => uiStorage.getSidebarWidth());
  const [listPanelWidth, setListPanelWidth] = useState(() => uiStorage.getListPanelWidth());
  // Инлайновая ширина ниже действует только на десктопе (lg:) — на узком
  // экране панели переключаются целиком через mobileView, там ширина не
  // при чём (w-full из tailwind-класса).
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia("(min-width: 1024px)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const handler = () => setIsDesktop(mq.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

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
      // screen=assistant — тот же маркер, который эффект-синхронизация
      // ниже теперь требует для вкладки "Ассистент" (см. selectDialog) —
      // прямая ссылка/PWA-ярлык на диалог без него не отличалась бы от
      // чата, открытого ИЗ просмотра заметок, и следующий же "назад"
      // уводил бы не туда.
      if (!searchParams.get("screen")) {
        setSearchParams(
          (prev) => {
            const next = new URLSearchParams(prev);
            next.set("screen", "assistant");
            return next;
          },
          { replace: true },
        );
      }
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
      setSearchParams(
        lastDialogId ? { dialog: lastDialogId, list: "1", screen: "assistant" } : { list: "1", screen: "assistant" },
      );
      return;
    }
    if (savedViewMode === "trash") {
      setViewModeState("trash");
      setSearchParams({ list: "1" });
      return;
    }
    if (savedViewMode === "documents") {
      setViewModeState("documents");
      // list: "1" — как у «Корзины» и «Активности»: на мобиле это
      // раскрывает список, иначе экран открывался бы пустым.
      setSearchParams({ list: "1" });
      return;
    }
    if (savedViewMode === "activity") {
      setViewModeState("activity");
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
    const screenParam = searchParams.get("screen");
    const nextMobileView: MobileView = itemParam || dialogParam ? "editor" : listParam ? "list" : "sidebar";
    setTransitionDirection(mobileView, nextMobileView);
    withViewTransition(
      () => {
        // viewMode не часть searchParams (это ось "Заметки/Ассистент/
        // Активность/Корзина", решение пользователя, не история одной
        // заметки) — сама по себе кнопка «назад»/popstate её не трогает.
        // Раньше это означало, что переход "Активность → заметка" или
        // "диалог → заметка" (см. onOpenItem/openRecentItem) и затем
        // «назад» возвращал item/dialog в URL правильно, но экран
        // оставался залипшим на viewMode="notes" — с dialogParam в URL,
        // но без AssistantChat на экране (реальный баг, найден при
        // проверке этой же фичи). item/dialog в URL однозначно
        // определяют нужный экран — остальные (Корзина/Активность)
        // своего item/dialog не имеют, поэтому их трогать не нужно.
        if (itemParam) setViewModeState("notes");
        else if (screenParam === "activity") setViewModeState("activity");
        else if (screenParam === "documents") setViewModeState("documents");
        else if (screenParam === "trash") setViewModeState("trash");
        // screen=assistant — тот же маркер для настоящего перехода на
        // вкладку "Ассистент" (см. selectDialog/switchToAssistant). Чат,
        // открытый ИЗ просмотра заметок (папка/заметка), его не ставит —
        // тогда dialogParam здесь есть, а screenParam нет, и viewMode
        // остаётся/восстанавливается как "notes" веткой listParam ниже —
        // ровно то, что нужно и при открытии, и при "назад" на этот же
        // ?list=1 (реальная жалоба: раньше "назад" из такого чата уводил
        // в список ВСЕХ чатов ассистента вместо папки, откуда вышли).
        else if (screenParam === "assistant") setViewModeState("assistant");
        // Без этой ветки viewMode, once switched to "assistant"/"activity"/
        // "trash", никогда не восстанавливался обратно в "notes" при
        // возврате жестом "назад" на голый список (?list=1, без item/
        // screen) — список рисовался как DialogList/ActivityView/
        // TrashView вместо NoteList той папки, откуда реально вышли.
        else if (listParam) setViewModeState("notes");
        setSelectedItemIdState(itemParam);
        setSelectedDialogId(dialogParam);
        setMobileView(nextMobileView);
      },
      // Реальная жалоба: этот переход двигает только мобильный стек
      // (sidebar/list/editor) — на lg: и шире все три панели видны
      // одновременно, снимать/анимировать нечего, а направленный слайд
      // выглядел как "весь интерфейс перерисовывается и едет вбок" без
      // причины. mobileOnly — см. viewTransition.ts.
      { mobileOnly: true },
    );
    if (activeSpaceId) uiStorage.setLastItemId(activeSpaceId, itemParam);
    uiStorage.setLastDialogId(dialogParam);
    // Пробы геометрии (search_params_sync_start/settled) убраны 10.10:
    // они ответили на свой вопрос. Ставились, чтобы проверить гипотезу
    // «белый экран из-за схлопнувшейся высоты dvh в Firefox Android», и
    // за два месяца собрали 6 881 замер — аномальная высота встретилась
    // в ТРЁХ. Гипотеза опровергнута, причина оказалась в компоузере
    // (см. forceRepaint.ts), а пробы продолжали писать по две строки в
    // журнал на каждую навигацию.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  function setViewMode(mode: ViewMode) {
    setViewModeState(mode);
    uiStorage.setViewMode(mode);
  }

  function setSelectedItemId(id: string | null, options?: { forcePush?: boolean; find?: string | null }) {
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
          // find — ТОЛЬКО в URL, и это единственный его источник.
          //
          // Первая версия держала его отдельным состоянием, и
          // внутриприложенческий путь не работал вовсе: openReminder
          // ставил состояние, тут же менял searchParams, а эффект
          // синхронизации по [searchParams] перезаписывал состояние
          // значением из URL, то есть null. Работала только холодная
          // ссылка из Telegram. Поймано ревью.
          //
          // Переход на ДРУГУЮ заметку параметр стирает: иначе, придя из
          // Telegram на ?item=A&find=10.12.2026 и щёлкнув заметку B, в
          // B подсвечивалась бы та же дата.
          if (options?.find) next.set("find", options.find);
          else next.delete("find");
        } else {
          next.delete("item");
          next.delete("find");
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
      // find привязан к конкретной заметке: уходим с неё — стираем,
      // иначе подсветка даты всплывёт на следующей открытой.
      next.delete("find");
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
  function openListView(screen?: "activity" | "trash" | "assistant" | "documents") {
    const alreadyOnList = mobileView === "list";
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("item");
        // find привязан к конкретной заметке: уходим с неё — стираем,
        // иначе подсветка даты всплывёт на следующей открытой.
        next.delete("find");
        next.delete("dialog");
        next.set("list", "1");
        // screen — маркер для Активности/Корзины (полноэкранные разделы без
        // своего item/dialog): без него popstate/«назад» из заметки,
        // открытой ИЗ активности, не мог понять, что viewMode нужно вернуть
        // в "activity", а не оставить как "notes" (реальный баг, найден при
        // добавлении центра активности — тот же класс, что и в
        // setSelectedItemId/selectDialog чуть выше, но для screen-уровня,
        // не item/dialog-уровня).
        if (screen) next.set("screen", screen);
        else next.delete("screen");
        return next;
      },
      alreadyOnList ? { replace: true } : undefined,
    );
  }

  // Кнопка «назад к списку спейсов» — тот же принцип, что closeItemView:
  // прямой replace, не полагается на глубину history.
  function closeListView() {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("item");
      // find привязан к конкретной заметке: уходим с неё — стираем,
      // иначе подсветка даты всплывёт на следующей открытой.
      next.delete("find");
      next.delete("dialog");
      next.delete("list");
      next.delete("screen");
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

  function openReminder(
    spaceId: string,
    itemId: string,
    entryId?: string,
    notificationId?: string,
    findText?: string,
  ) {
    setViewMode("notes");
    setActiveSpaceId(spaceId);
    setActiveFolderId(null);
    setTagId(null);
    setHighlightEntryId(entryId ?? null);
    // Список — подсветка по entryId (пункт списка). Заметка — по id самого
    // уведомления (см. ReminderAnchor.ts): якорь в заметке хранит именно
    // его, отдельный id для якоря не заводили, незачем.
    setHighlightAnchorId(entryId ? null : (notificationId ?? null));
    // findText уходит в URL вместе с item — см. комментарий в
    // setSelectedItemId про то, почему не в состояние.
    setSelectedItemId(itemId, { forcePush: true, find: findText ?? null });
  }

  function selectTag(id: string | null) {
    setViewMode("notes");
    setTagId(id);
    openListView();
  }

  function switchToAssistant() {
    setViewMode("assistant");
    openListView("assistant");
  }

  function switchToTrash() {
    setViewMode("trash");
    openListView("trash");
  }

  function switchToActivity() {
    setViewMode("activity");
    openListView("activity");
  }

  function switchToDocuments() {
    setViewMode("documents");
    openListView("documents");
  }

  function openRecentItem(spaceId: string, itemId: string) {
    setViewMode("notes");
    setActiveSpaceId(spaceId);
    setActiveFolderId(null);
    setTagId(null);
    setSelectedItemId(itemId, { forcePush: true });
  }

  function openRecentDialog(id: string) {
    setViewMode("assistant");
    selectDialog(id, { forcePush: true });
  }

  function selectDialog(id: string | null, options?: { forcePush?: boolean; keepViewMode?: boolean }) {
    // Тот же принцип, что в setSelectedItemId/openListView.
    const alreadyOnEditor = mobileView === "editor" && !options?.forcePush;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (id) {
          next.set("dialog", id);
          next.set("list", "1");
          next.delete("item");
          // find привязан к конкретной заметке: уходим с неё — стираем,
          // иначе подсветка даты всплывёт на следующей открытой.
          next.delete("find");
          // Реальный найденный баг: чат ассистента по папке/заметке
          // открывается ИЗНУТРИ обычного просмотра заметок (viewMode
          // "notes"), а не с вкладки "Ассистент" — но эффект синхронизации
          // ниже раньше слепо переключал viewMode на "assistant" для
          // ЛЮБОГО dialog в URL. Дальше жест "назад" уводил на предыдущую
          // запись истории (?list=1, без screen) — viewMode ничем не
          // восстанавливался и оставался "assistant": список рисовался
          // как DialogList (все чаты) вместо NoteList той папки, откуда
          // реально вышли. screen=assistant — тот же маркер, которым уже
          // помечены Активность/Корзина (openListView) — переиспользуем
          // его и для настоящего перехода на вкладку "Ассистент", а
          // чатам, открытым ИЗ просмотра заметок (keepViewMode), его не
          // ставим — тогда попадание на голый ?list=1 при "назад"
          // однозначно восстанавливает viewMode "notes" (см. эффект ниже).
          if (options?.keepViewMode) next.delete("screen");
          else next.set("screen", "assistant");
        } else {
          next.delete("dialog");
        }
        return next;
      },
      alreadyOnEditor ? { replace: true } : undefined,
    );
  }

  function toggleSpaceCollapsed(spaceId: string) {
    // Реальный найденный источник "дёргания": это локальное раскрытие ОДНОЙ
    // записи в уже видимом сайдбаре, не переход между экранами/панелями —
    // startViewTransition() снимает ДВА снимка ВСЕЙ страницы и слайдит/
    // затемняет их поверх друг друга
    // (::view-transition-old/new(root) в index.css — по умолчанию таргет
    // именно root целиком, у SpaceSection нет своего view-transition-name).
    // Это соревновалось с локальной CSS-анимацией высоты в SpaceSection.tsx
    // (grid-template-rows) на одном и том же участке экрана — два независимых
    // анимационных механизма поверх друг друга и есть тот самый рывок,
    // который чинили раньше вслепую на уровне CSS, хотя источник был здесь.
    setCollapsedSpaces((prev) => {
      const next = new Set(prev);
      if (next.has(spaceId)) next.delete(spaceId);
      else next.add(spaceId);
      uiStorage.setCollapsedSpaces(Array.from(next));
      return next;
    });
  }

  function toggleSidebar() {
    // Раньше был обёрнут в withViewTransition — тот же баг, что чинили в
    // toggleSpaceCollapsed: снимок ВСЕЙ страницы поверх обычного изменения
    // ширины одной панели (реальная жалоба: "дёргается и перерисовывается
    // весь интерфейс" при сворачивании). Теперь ширина — числовое
    // состояние (см. sidebarWidth ниже), а не display:none/flex, поэтому
    // сворачивание анимируется обычным CSS-переходом width, без снимков.
    setSidebarCollapsed((v) => {
      const next = !v;
      uiStorage.setSidebarCollapsed(next);
      return next;
    });
  }

  function toggleList() {
    setListCollapsed((v) => {
      const next = !v;
      uiStorage.setListCollapsed(next);
      return next;
    });
  }

  const sidebarHandle = useResizeHandle({
    width: sidebarWidth,
    collapsed: sidebarCollapsed,
    min: 200,
    max: 420,
    onResize: (next) => {
      setSidebarWidth(next);
      uiStorage.setSidebarWidth(next);
    },
  });
  const listHandle = useResizeHandle({
    width: listPanelWidth,
    collapsed: listCollapsed,
    min: 240,
    max: 560,
    onResize: (next) => {
      setListPanelWidth(next);
      uiStorage.setListPanelWidth(next);
    },
  });

  return (
    <div
      ref={rootRef}
      // Колонка, а не только ряд: сверху узкая полоска «нет сети», под
      // ней — прежняя горизонтальная раскладка.
      className="flex h-dvh flex-col bg-app text-primary"
      style={{
        boxSizing: "border-box",
        paddingTop: "var(--safe-top)",
        paddingRight: "var(--safe-right)",
        paddingBottom: "var(--safe-bottom)",
        paddingLeft: "var(--safe-left)",
      }}
    >
      {/* Реальный найденный инцидент (2026-08-19): устаревшая открытая
          вкладка молча продолжала автосохранять заметку СВОИМ, давно не
          обновлявшимся локальным состоянием — трижды за день затирала
          то, что только что восстановили в свежей вкладке. Раньше признак
          новой версии был спрятан пунктом в выпадающем списке колокольчика
          (NotificationBell) — то, что реально нужно было заметить, чтобы
          не потерять данные, было легко не увидеть вовсе. Баннер во всю
          ширину экрана, поверх всего — не пропустить, не нужно открывать
          колокольчик, чтобы узнать. См. NoteEditor.tsx — автосейв там
          дополнительно сам отказывается писать на сервер, пока баннер
          виден, даже если его никто не заметил.*/}
      {updateAvailable && (
        <div className="fixed inset-x-0 top-0 z-[100] flex flex-wrap items-center justify-center gap-2 bg-warning px-3 py-2 text-center text-sm font-medium text-white shadow">
          Доступна новая версия — эта вкладка устарела и больше не сохраняет правки, чтобы не затереть чужие.
          <button
            onClick={() => window.location.reload()}
            className="rounded bg-surface px-3 py-1 text-xs font-semibold text-warning hover:bg-warning/10"
          >
            Обновить страницу
          </button>
        </div>
      )}

      <OfflineBanner />
      <OfflineFlushNotice />
      {/* Реальный найденный баг: тут раньше был overflow-x-hidden (чтобы
          контент не вылезал вбок во время анимации ширины) — но CSS
          вычисляет overflow-y как auto вместо visible, если overflow-x
          задан НЕ visible, а overflow-y явно не указан (спека: "visible"
          на одной оси при не-"visible" на другой считается как "auto").
          Это молча обрезало любой попап, всплывающий ЗА пределы панели по
          вертикали — выпадающее меню шаблонов заметки (NoteTemplateMenu)
          рисовалось, но было невидимым и съедало следующий клик своим
          fixed-бэкдропом. Косметика ширины не стоила этой цены — убрано. */}
      <div className="flex min-h-0 flex-1">
      <aside
        className={`${mobileView === "sidebar" ? "flex" : "hidden"} w-full shrink-0 flex-col border-r bg-muted lg:flex`}
        style={
          isDesktop
            ? { width: sidebarCollapsed ? 0 : sidebarWidth, transition: "width 180ms ease-out" }
            : undefined
        }
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
                viewMode === "assistant" ? "bg-muted-active font-medium text-primary" : "text-secondary hover:bg-muted-hover"
              }`}
            >
              <Sparkles size={15} /> Ассистент
            </button>
            <button
              onClick={switchToActivity}
              className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm ${
                viewMode === "activity" ? "bg-muted-active font-medium text-primary" : "text-secondary hover:bg-muted-hover"
              }`}
            >
              <Bell size={15} /> Активность
            </button>
            <button
              onClick={switchToDocuments}
              className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm ${
                viewMode === "documents" ? "bg-muted-active font-medium text-primary" : "text-secondary hover:bg-muted-hover"
              }`}
            >
              <FileStack size={15} /> Документы
            </button>
            <button
              onClick={switchToTrash}
              className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm ${
                viewMode === "trash" ? "bg-muted-active font-medium text-primary" : "text-secondary hover:bg-muted-hover"
              }`}
            >
              <Trash2 size={15} /> Корзина
            </button>
          </div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wide text-subtle">Спейсы</span>
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

      {/* Реальная жалоба: раньше это была одна большая (во всю высоту)
          кликабельная кнопка, совмещавшая ресайз и сворачивание — тянуть
          и кликать по одному и тому же большому элементу было неудобно и
          неочевидно, к тому же наведение мышкой само по себе (без нажатия)
          иногда двигало ширину — pointermove у браузера срабатывает и без
          зажатой кнопки, useResizeHandle это чинит явным флагом (см. lib/
          useResizablePanel.ts). Теперь как в Confluence/Jira: тонкая
          полоска — только ресайз перетаскиванием, поверх неё маленькая
          круглая кнопка посередине — только сворачивание кликом.
          Реальный найденный баг: кнопка была ВЛОЖЕНА в полоску — клик по
          ней всё равно всплывал до pointerdown полоски, та вызывала
          setPointerCapture НА СЕБЯ, и последующий click ретаргетился на
          неё же вместо кнопки (спека Pointer Events) — кнопка визуально
          была на месте, но ничего не нажималось. Полоска и кнопка теперь
          СЁСТРЫ (не родитель/потомок) внутри общего relative-обёртки —
          события одной больше не проходят через другую. */}
      <div className="relative hidden w-2 shrink-0 lg:block">
        <div
          {...sidebarHandle}
          title="Потяните, чтобы изменить ширину панели"
          className="absolute inset-0 cursor-col-resize touch-none border-r bg-muted hover:bg-muted-active"
        />
        <button
          onClick={toggleSidebar}
          title={sidebarCollapsed ? "Показать панель" : "Скрыть панель"}
          className="absolute left-1/2 top-1/2 z-10 flex h-6 w-6 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border bg-surface text-subtle shadow-sm hover:text-secondary"
        >
          {sidebarCollapsed ? <ChevronRight size={13} /> : <ChevronLeft size={13} />}
        </button>
      </div>

      <main className="flex min-h-0 flex-1 overflow-hidden">
        {viewMode === "trash" ? (
          <TrashView spaceId={activeSpaceId} onBack={closeListView} />
        ) : viewMode === "documents" ? (
          <DocumentsView onBack={closeListView} onOpenItem={openRecentItem} />
        ) : viewMode === "activity" ? (
          <ActivityView
            onBack={closeListView}
            onOpenReminder={openReminder}
            onOpenItem={openRecentItem}
            onOpenDialog={openRecentDialog}
          />
        ) : (
          <>
            {/* overflow-x-hidden убран тут же и по той же причине, что у
                aside выше — этот блок держит NoteTemplateMenu. */}
            <div
              className={`${mobileView === "list" ? "flex" : "hidden"} w-full shrink-0 flex-col border-r lg:flex`}
              style={
                isDesktop
                  ? { width: listCollapsed ? 0 : listPanelWidth, transition: "width 180ms ease-out" }
                  : undefined
              }
            >
              {viewMode === "notes" ? (
                <>
                  <div className="flex items-center gap-1 border-b p-3">
                    <button
                      onClick={closeListView}
                      className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-subtle lg:hidden"
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <SearchBar value={query} onChange={setQuery} />
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto">
                    {query.trim() ? (
                      <SearchResults query={query} selectedId={selectedItemId} onSelect={setSelectedItemId} />
                    ) : activeSpaceId && activeVaultLocked && activeSpace ? (
                      <VaultUnlockOverlay spaceId={activeSpace.id} spaceName={activeSpace.name} />
                    ) : activeSpaceId ? (
                      <NoteList
                        spaceId={activeSpaceId}
                        folderId={activeFolderId}
                        tagId={tagId}
                        selectedId={selectedItemId}
                        onSelect={setSelectedItemId}
                        onSelectDialog={(id) => selectDialog(id, { forcePush: true, keepViewMode: true })}
                        isVault={!!activeSpace?.is_vault}
                      />
                    ) : (
                      <div className="p-3 text-sm text-subtle">Нет доступных спейсов</div>
                    )}
                  </div>
                </>
              ) : (
                <>
                  <div className="flex items-center gap-1 border-b p-3 lg:hidden">
                    <button
                      onClick={closeListView}
                      className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-subtle"
                    >
                      <ChevronLeft size={18} />
                    </button>
                    <span className="text-sm font-medium text-primary">Ассистент</span>
                  </div>
                  <DialogList selectedId={selectedDialogId} onSelect={selectDialog} />
                </>
              )}
            </div>

            <div className="relative hidden w-2 shrink-0 lg:block">
              <div
                {...listHandle}
                title="Потяните, чтобы изменить ширину списка"
                className="absolute inset-0 cursor-col-resize touch-none border-r bg-surface hover:bg-muted-hover"
              />
              <button
                onClick={toggleList}
                title={listCollapsed ? "Показать список" : "Скрыть список"}
                className="absolute left-1/2 top-1/2 z-10 flex h-6 w-6 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border bg-surface text-subtle shadow-sm hover:text-secondary"
              >
                {listCollapsed ? <ChevronRight size={13} /> : <ChevronLeft size={13} />}
              </button>
            </div>

            <div className={`${mobileView === "editor" ? "flex" : "hidden"} lg:flex min-h-0 flex-1 flex-col overflow-hidden`}>
              {/* Реальный найденный баг: раньше здесь ветвили по viewMode
                  ("notes" → ItemView, иначе → AssistantChat) — но чат по
                  папке/заметке (см. selectDialog/keepViewMode) намеренно
                  оставляет viewMode "notes", хотя открыт именно диалог, не
                  заметка. Ветвим напрямую по тому, что реально выбрано —
                  item/dialog взаимоисключающи по построению (selectDialog
                  всегда снимает item, setSelectedItemId всегда снимает
                  dialog), так что порядок проверки однозначен независимо
                  от viewMode. */}
              {selectedItemId ? (
                <ItemView
                  itemId={selectedItemId}
                  onDeleted={closeItemView}
                  onBack={closeItemView}
                  highlightEntryId={highlightEntryId}
                  highlightAnchorId={highlightAnchorId}
                  findText={findText}
                  onOpenItem={(id) => {
                    setViewMode("notes");
                    setActiveFolderId(null);
                    setTagId(null);
                    setSelectedItemId(id, { forcePush: true });
                  }}
                />
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
              ) : viewMode === "notes" ? (
                <div className="flex h-full items-center justify-center text-subtle">
                  Выберите заметку слева или создайте новую
                </div>
              ) : (
                <div className="flex h-full items-center justify-center text-subtle">
                  Выберите диалог слева или создайте новый
                </div>
              )}
            </div>
          </>
        )}
      </main>
      </div>
    </div>
  );
}

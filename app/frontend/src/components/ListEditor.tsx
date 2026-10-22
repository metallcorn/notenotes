import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { ArrowDown, ChevronLeft, History, MoreVertical, Plus, Trash2, X } from "lucide-react";
import { t } from "../i18n";
import { useAddListEntry, useDeleteItem, useDeleteListEntry, useList, useUpdateItem, useUpdateListEntry } from "../api/hooks";
import type { ListEntry } from "../api/types";
import { useListSync } from "../lib/useListSync";
import ConfirmDialog from "./ConfirmDialog";
import Spinner from "./Spinner";
import VersionHistoryPanel from "./VersionHistoryPanel";

// Пункт списка раньше был ВСЕГДА голым <input> — раз это <input value=...>,
// внутри него физически не может быть настоящего <a>, поэтому markdown-
// ссылка [текст](url), которую туда кладёт ассистент (create_list/
// add_list_entry — тексту в entries негде больше стать ссылкой, у списков
// нет своего markdown-рендера, как у заметок), так и оставалась голым
// текстом со скобками — реальная жалоба ("ссылки некликабельные"). Без
// полноценного markdown-редактора: просто вытаскиваем [текст](url) и голые
// http(s)-ссылки регэкспом и рисуем как <a>, обычный текст — как есть.
const _MD_LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;
const _BARE_URL_RE = /(https?:\/\/\S+)/g;

export function renderEntryText(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  for (const m of text.matchAll(_MD_LINK_RE)) {
    if (m.index! > lastIndex) nodes.push(text.slice(lastIndex, m.index));
    nodes.push(
      <a
        key={key++}
        href={m[2]}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="text-link underline hover:text-link"
      >
        {m[1]}
      </a>,
    );
    lastIndex = m.index! + m[0].length;
  }
  const rest = text.slice(lastIndex);
  // Голые http(s)-ссылки (без markdown-обёртки, например когда ассистент
  // просто дописал URL текстом после названия, а не оформил [текст](url))
  // — тем же приёмом, отдельным проходом, чтобы не пересекаться с уже
  // найденными markdown-ссылками выше. Текстом ссылки — ТОЛЬКО домен, не
  // весь URL: реальная жалоба — голый длинный URL как текст ссылки не
  // помещался в строку пункта (особенно на телефоне) и обрезался до
  // нечитаемого/некликабельного огрызка вроде "https:/…".
  let restLast = 0;
  for (const m of rest.matchAll(_BARE_URL_RE)) {
    if (m.index! > restLast) nodes.push(rest.slice(restLast, m.index));
    let label = m[0];
    try {
      label = new URL(m[0]).hostname.replace(/^www\./, "");
    } catch {
      // Некорректный URL — оставляем как есть, не должно происходить, но
      // не пытаемся падать на этом.
    }
    nodes.push(
      <a
        key={key++}
        href={m[0]}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="text-link underline hover:text-link"
      >
        {label}
      </a>,
    );
    restLast = m.index! + m[0].length;
  }
  if (restLast < rest.length) nodes.push(rest.slice(restLast));
  return nodes;
}

function ListEntryRow({
  entry,
  onToggle,
  onTextChange,
  onDelete,
}: {
  entry: ListEntry;
  onToggle: (checked: boolean) => void;
  onTextChange: (text: string) => void;
  onDelete: () => void;
}) {
  const [text, setText] = useState(entry.text);
  const [editing, setEditing] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => setText(entry.text), [entry.text]);

  function saveText() {
    const trimmed = text.trim();
    if (trimmed && trimmed !== entry.text) onTextChange(trimmed);
    else if (!trimmed) setText(entry.text);
    setEditing(false);
  }

  const hasLink = _MD_LINK_RE.test(entry.text) || _BARE_URL_RE.test(entry.text);
  // .test() на regexp с флагом /g двигает lastIndex — сбрасываем, иначе
  // следующий вызов hasLink для того же текста будет случайно false.
  _MD_LINK_RE.lastIndex = 0;
  _BARE_URL_RE.lastIndex = 0;

  return (
    <li
      id={`list-entry-${entry.id}`}
      className="group flex min-h-[52px] items-center gap-3 rounded-xl px-2.5 py-1 transition-colors duration-500"
    >
      {/* Крупный чекбокс со скруглёнными углами (макет «Список-чеклист»,
          21.10): на телефоне в 16px попасть пальцем трудно. Настоящий
          <input> остаётся ради клавиатуры и читалок, рисуется поверх него. */}
      <label className="relative flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center">
        <input
          type="checkbox"
          checked={entry.checked}
          onChange={(e) => onToggle(e.target.checked)}
          className="peer absolute inset-0 h-full w-full cursor-pointer opacity-0"
        />
        <span
          aria-hidden="true"
          className="flex h-[26px] w-[26px] items-center justify-center rounded-[9px] border-[2.5px] border-strong bg-surface text-on-accent transition-colors peer-checked:border-brand peer-checked:bg-brand peer-focus-visible:ring-2 peer-focus-visible:ring-brand/40"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" className={entry.checked ? "" : "opacity-0"}>
            <path d="M5 12l5 5L20 7" />
          </svg>
        </span>
      </label>
      {editing || !hasLink ? (
        <input
          ref={inputRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={saveText}
          onKeyDown={(e) => {
            if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          }}
          className={`min-w-0 flex-1 border-none bg-transparent text-base font-bold outline-none ${
            entry.checked ? "text-subtle line-through" : "text-primary"
          }`}
        />
      ) : (
        <div
          onClick={() => setEditing(true)}
          className={`min-w-0 flex-1 cursor-text truncate text-base font-bold ${
            entry.checked ? "text-subtle line-through" : "text-primary"
          }`}
        >
          {renderEntryText(text)}
        </div>
      )}
      <button
        onClick={onDelete}
        title="Удалить пункт"
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-subtle hover:bg-muted hover:text-danger"
      >
        <X size={14} />
      </button>
    </li>
  );
}

export default function ListEditor({
  itemId,
  onDeleted,
  onBack,
  highlightEntryId,
}: {
  itemId: string;
  onDeleted: () => void;
  onBack: () => void;
  highlightEntryId?: string | null;
}) {
  const { data: list } = useList(itemId);
  useListSync(itemId);

  // Переход из напоминания (create_reminder) — прокрутить к конкретному
  // пункту и подсветить. highlightedRef, а не просто зависимость от
  // highlightEntryId — иначе каждый refetch списка (поллинг раз в минуту у
  // уведомлений тут ни при чём, но список синкается по WS) переигрывал бы
  // подсветку заново, пока пользователь сидит на этой странице.
  const highlightedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!highlightEntryId || !list) return;
    if (highlightedRef.current === highlightEntryId) return;
    highlightedRef.current = highlightEntryId;
    const el = document.getElementById(`list-entry-${highlightEntryId}`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("bg-warning/15");
    setTimeout(() => el.classList.remove("bg-warning/15"), 2500);
  }, [highlightEntryId, list]);

  const updateItem = useUpdateItem();
  const deleteItem = useDeleteItem(list?.space_id);
  const addEntry = useAddListEntry(itemId);
  const updateEntry = useUpdateListEntry(itemId);
  const deleteEntry = useDeleteListEntry(itemId);

  const [title, setTitle] = useState("");
  const [newEntryText, setNewEntryText] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [syncedId, setSyncedId] = useState<string | null>(null);
  const newEntryInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (list && syncedId !== list.id) {
      setTitle(list.title);
      setSyncedId(list.id);
    }
  }, [list, syncedId]);

  function saveTitle() {
    if (list && title.trim() && title !== list.title) {
      updateItem.mutate({ id: list.id, title: title.trim() });
    }
  }

  async function handleAddEntry(e: FormEvent) {
    e.preventDefault();
    const text = newEntryText.trim();
    if (!text || addEntry.isPending) return;
    setNewEntryText("");
    await addEntry.mutateAsync(text);
  }

  if (!list) {
    return (
      <div className="flex h-full items-center justify-center text-subtle">
        <Spinner />
      </div>
    );
  }

  const doneCount = list.entries.filter((e) => e.checked).length;
  const open = list.entries.filter((e) => !e.checked);
  const done = list.entries.filter((e) => e.checked);
  const row = (entry: ListEntry) => (
    <ListEntryRow
      key={entry.id}
      entry={entry}
      onToggle={(checked) => updateEntry.mutate({ entryId: entry.id, checked })}
      onTextChange={(text) => updateEntry.mutate({ entryId: entry.id, text })}
      onDelete={() => deleteEntry.mutate(entry.id)}
    />
  );

  return (
    <div className="flex h-full">
    <div className="relative flex min-w-0 flex-1 flex-col">
      {/* Шапка (макет «Список-чеклист», 21.10): назад, подпись, «⋯» на
          телефоне; на десктопе — те же действия отдельными кнопками. */}
      <div className="flex flex-wrap items-center gap-2 p-3 lg:flex-nowrap lg:border-b">
        <button
          onClick={onBack}
          aria-label={t("nav.back")}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card lg:hidden"
        >
          <ChevronLeft size={20} strokeWidth={2.4} />
        </button>
        <div className="min-w-0 flex-1 truncate pl-1 text-[13px] font-bold text-subtle lg:hidden">{t("create.list")}</div>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          onBlur={saveTitle}
          placeholder="Название списка"
          className="order-last mt-1 w-full min-w-0 border-none bg-transparent px-2 text-[28px] font-extrabold leading-tight tracking-tight text-primary outline-none placeholder:text-subtle lg:order-none lg:mt-0 lg:w-auto lg:flex-1 lg:truncate lg:px-0 lg:text-xl"
        />
        <button
          onClick={() => setShowHistory((v) => !v)}
          title="История версий"
          className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl text-subtle hover:bg-muted hover:text-secondary lg:flex"
        >
          <History size={16} />
        </button>
        <button
          title="Удалить список"
          onClick={() => setConfirmingDelete(true)}
          className="hidden h-9 w-9 shrink-0 items-center justify-center rounded-xl text-subtle hover:bg-muted hover:text-danger lg:flex"
        >
          <Trash2 size={16} />
        </button>
        <div className="relative shrink-0 lg:hidden">
          <button
            onClick={() => setMenuOpen((v) => !v)}
            title="Действия со списком"
            className="flex h-11 w-11 items-center justify-center rounded-2xl bg-surface text-primary shadow-card"
          >
            <MoreVertical size={20} />
          </button>
          {menuOpen && (
            <>
              <div className="fixed inset-0 z-20" onClick={() => setMenuOpen(false)} />
              <div className="absolute right-0 top-full z-30 mt-1 w-52 overflow-hidden rounded-2xl border bg-surface py-1.5 shadow-lg">
                <button
                  onClick={() => {
                    setShowHistory((v) => !v);
                    setMenuOpen(false);
                  }}
                  className="flex min-h-10 w-full items-center gap-2.5 px-4 text-left text-sm font-semibold text-secondary hover:bg-muted"
                >
                  <History size={14} /> История версий
                </button>
                <button
                  onClick={() => {
                    setConfirmingDelete(true);
                    setMenuOpen(false);
                  }}
                  className="flex min-h-10 w-full items-center gap-2.5 px-4 text-left text-sm font-bold text-danger hover:bg-danger-soft"
                >
                  <Trash2 size={14} /> Удалить список
                </button>
              </div>
            </>
          )}
        </div>
      </div>
      {list.entries.length > 0 && (
        <div className="flex items-center gap-2.5 px-5 pb-1 pt-3 lg:px-4">
          <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-brand transition-[width] duration-300"
              style={{ width: `${Math.round((doneCount / list.entries.length) * 100)}%` }}
            />
          </div>
          <span className="shrink-0 text-sm font-extrabold text-primary">
            {t("list.progress", { done: doneCount, total: list.entries.length })}
          </span>
        </div>
      )}
      <div className="flex-1 overflow-y-auto p-3 pb-24">
        {list.entries.length === 0 ? (
          // Реальная жалоба: пустой список выглядел как "тут ничего не
          // работает" — не было понятно, что пункты добавляются полем
          // ввода СНИЗУ, а не кликом по самой пустой области списка.
          <button
            onClick={() => newEntryInputRef.current?.focus()}
            className="flex h-full w-full flex-col items-center justify-center gap-2 p-3 text-center text-sm text-subtle"
          >
            <div>Пока пусто</div>
            <div className="flex items-center gap-1 text-xs">
              Введите текст пункта в поле внизу
              <ArrowDown size={14} className="animate-bounce" />
            </div>
          </button>
        ) : (
          <>
            {open.length > 0 && <ul className="rounded-3xl bg-surface p-1.5 shadow-card">{open.map(row)}</ul>}
            {done.length > 0 && (
              <>
                <div className="px-3 pb-1.5 pt-4 text-[11px] font-extrabold uppercase tracking-wider text-subtle">
                  {t("list.done")} · {done.length}
                </div>
                <ul className="px-1.5">{done.map(row)}</ul>
              </>
            )}
          </>
        )}
      </div>

      {/* Плавающая строка добавления (макет): поле + лаймовый «+». */}
      <div className="pointer-events-none absolute inset-x-3 bottom-3 z-10 lg:static lg:inset-auto lg:p-3">
        <form
          onSubmit={handleAddEntry}
          className="pointer-events-auto flex gap-2 rounded-3xl bg-surface p-1.5 shadow-float"
        >
          <input
            ref={newEntryInputRef}
            value={newEntryText}
            onChange={(e) => setNewEntryText(e.target.value)}
            placeholder={t("list.addItem")}
            className="h-12 min-w-0 flex-1 rounded-2xl bg-transparent px-3 text-base outline-none"
          />
          <button
            type="submit"
            aria-label="Добавить пункт"
            disabled={addEntry.isPending || !newEntryText.trim()}
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-lime text-on-lime disabled:opacity-50"
          >
            {addEntry.isPending ? <Spinner size={14} /> : <Plus size={22} strokeWidth={2.8} />}
          </button>
        </form>
      </div>

      {confirmingDelete && (
        <ConfirmDialog
          title={`Удалить список «${list.title || "без названия"}»? Он переместится в корзину.`}
          danger
          onConfirm={() => {
            deleteItem.mutate(list.id);
            setConfirmingDelete(false);
            onDeleted();
          }}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}
    </div>
    {showHistory && <VersionHistoryPanel itemId={list.id} onClose={() => setShowHistory(false)} />}
    </div>
  );
}

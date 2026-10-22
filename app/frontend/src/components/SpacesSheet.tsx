import { Suspense, lazy, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronRight, FileStack, GripVertical, Lock, Tag as TagIcon, Trash2 } from "lucide-react";
import type { Space } from "../api/types";
import { useFolders, useReorderSpaces, useSpaceMembers, useUpdateSpace } from "../api/hooks";
import { useVaultUnlocked } from "../lib/vaultSession";
import { useDragReorder } from "../lib/useDragReorder";

const EmojiPickerPopover = lazy(() => import("./EmojiPickerPopover"));
import CreateSpaceButton from "./CreateSpaceButton";
import { t, tn } from "../i18n";

// Цвета плиток-инициалов по порядку спейсов: активный — лайм, остальные
// чередуются мягкими подложками (макет «Спейсы», 21.10).
const TILE_STYLES = ["bg-brand-soft text-brand-text", "bg-[#DCEBFF] text-[#1D4ED8]", "bg-[#FDE9DF] text-[#B4441B]", "bg-success-soft text-success"];

function SpaceRow({
  space,
  index,
  active,
  dragging,
  handle,
  onPick,
}: {
  space: Space;
  index: number;
  active: boolean;
  dragging: boolean;
  handle: Record<string, unknown>;
  onPick: () => void;
}) {
  const { data: folders } = useFolders(space.id);
  const { data: members } = useSpaceMembers(space.id);
  const updateSpace = useUpdateSpace();
  const unlocked = useVaultUnlocked(space.is_vault ? space.id : undefined);
  const [pickerOpen, setPickerOpen] = useState(false);
  const initial = (space.name.trim()[0] ?? "?").toUpperCase();
  const others = (members ?? []).slice(0, 3);
  // Плитка — тап открывает пикер значка; «ручка» справа — перетаскивание.
  const tile = (cls: string, content: React.ReactNode) => (
    <span className="relative shrink-0">
      <button
        type="button"
        aria-label={`Значок спейса «${space.name}»`}
        onClick={(e) => {
          e.stopPropagation();
          setPickerOpen((v) => !v);
        }}
        className={`flex h-12 w-12 items-center justify-center rounded-2xl text-[22px] font-extrabold leading-none ${cls}`}
      >
        {space.icon ?? content}
      </button>
      {pickerOpen && (
        <Suspense fallback={null}>
          <EmojiPickerPopover
            onSelect={(emoji) => updateSpace.mutate({ id: space.id, icon: emoji })}
            onClose={() => setPickerOpen(false)}
          />
        </Suspense>
      )}
    </span>
  );
  const grip = (cls: string) => (
    <span
      {...handle}
      aria-label="Перетащить"
      role="button"
      className={`flex h-12 w-9 shrink-0 cursor-grab touch-none items-center justify-center ${cls}`}
    >
      <GripVertical size={18} />
    </span>
  );
  const rowCls = dragging ? "scale-[1.02] shadow-float" : "";

  if (space.is_vault) {
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={onPick}
        onKeyDown={(e) => e.key === "Enter" && onPick()}
        className={`flex w-full items-center gap-3 rounded-2xl bg-nav p-3 pr-1 text-left text-nav-text transition-transform ${active ? "ring-2 ring-lime" : ""} ${rowCls}`}
      >
        {tile("bg-white/10 text-lime", <Lock size={22} strokeWidth={2.2} />)}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-base font-extrabold">{space.name}</span>
          <span className="block text-[13px] font-semibold text-nav-muted">
            {unlocked ? t("spaces.vaultOpen") : t("spaces.vaultLocked")}
          </span>
        </span>
        <ChevronRight size={18} className="shrink-0 text-nav-muted" />
        {grip("text-nav-muted")}
      </div>
    );
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onPick}
      onKeyDown={(e) => e.key === "Enter" && onPick()}
      className={`flex w-full items-center gap-3 rounded-2xl p-3 pr-1 text-left text-primary transition-transform ${
        active ? "border-2 border-primary bg-surface" : "bg-muted hover:bg-muted-hover"
      } ${rowCls}`}
    >
      {tile(active ? "bg-lime text-on-lime" : TILE_STYLES[index % TILE_STYLES.length], initial)}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-base font-extrabold">{space.name}</span>
        <span className="block text-[13px] font-semibold text-subtle">
          {folders ? tn("count.folders", folders.length) : "…"}
          {members && members.length > 1 ? ` · ${tn("count.members", members.length)}` : ""}
        </span>
      </span>
      {others.length > 1 && (
        <span className="flex shrink-0" aria-hidden="true">
          {others.map((m, i) => (
            <span
              key={m.user_id}
              className={`flex h-7 w-7 items-center justify-center rounded-full border-2 border-surface text-xs font-extrabold ${
                i === 0 ? "bg-brand text-white" : "bg-[#F2A65A] text-on-lime"
              } ${i > 0 ? "-ml-2" : ""}`}
            >
              {(m.name || m.username).trim()[0]?.toUpperCase() ?? "?"}
            </span>
          ))}
        </span>
      )}
      {grip("text-subtle")}
    </div>
  );
}

// Шторка «Спейсы» (макет 21.10): список спейсов строками с инициалом,
// числом папок и участниками; сейф — тёмной строкой. Снизу — Корзина,
// Документы, Теги: на телефоне у них нет своей кнопки в нижней панели.
export default function SpacesSheet({
  spaces,
  activeSpaceId,
  onPick,
  onCreated,
  onTrash,
  onDocuments,
  onTags,
  onClose,
}: {
  spaces: Space[];
  activeSpaceId: string | undefined;
  onPick: (space: Space) => void;
  onCreated: (spaceId: string) => void;
  onTrash: () => void;
  onDocuments: () => void;
  onTags: () => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const reorder = useReorderSpaces();
  const drag = useDragReorder(spaces, (ids) => reorder.mutate(ids));

  const bottom = (label: string, Icon: typeof Trash2, onClick: () => void) => (
    <button
      type="button"
      onClick={onClick}
      className="flex h-12 flex-1 items-center justify-center gap-1.5 rounded-2xl border-[1.5px] border-default bg-surface text-sm font-bold text-primary hover:bg-muted"
    >
      <Icon size={16} /> {label}
    </button>
  );

  return createPortal(
    <div
      className="modal-in fixed inset-0 z-50 flex items-end justify-center bg-black/45 sm:items-center sm:p-4"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={t("spaces.title")}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="sheet-in flex max-h-[88dvh] w-full max-w-md flex-col rounded-t-3xl bg-surface px-4 pb-[max(20px,var(--safe-bottom))] pt-2.5 shadow-xl sm:rounded-3xl sm:pb-5"
      >
        <div className="mx-auto mb-3 h-[5px] w-10 shrink-0 rounded-full bg-muted-active sm:hidden" aria-hidden="true" />
        <div className="flex shrink-0 items-center justify-between px-1 pb-2.5">
          <h2 className="text-2xl font-extrabold tracking-tight text-primary">{t("spaces.title")}</h2>
          <CreateSpaceButton
            variant="pill"
            onCreated={(id) => {
              onCreated(id);
              onClose();
            }}
          />
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
          {spaces.map((space, i) => (
            <div key={space.id} ref={drag.register(space.id)} style={drag.styleFor(space.id)}>
              <SpaceRow
                space={space}
                index={i}
                active={space.id === activeSpaceId}
                dragging={drag.draggingId === space.id}
                handle={drag.handle(space.id)}
                onPick={() => {
                  if (drag.draggingId) return;
                  onPick(space);
                  onClose();
                }}
              />
            </div>
          ))}
        </div>
        <div className="mt-3.5 flex shrink-0 gap-2">
          {bottom(t("nav.trash"), Trash2, () => {
            onTrash();
            onClose();
          })}
          {bottom(t("nav.documents"), FileStack, () => {
            onDocuments();
            onClose();
          })}
          {bottom(t("nav.tags"), TagIcon, () => {
            onTags();
            onClose();
          })}
        </div>
      </div>
    </div>,
    document.body,
  );
}

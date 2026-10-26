import { useRef } from "react";
import { useItem } from "../api/hooks";
import type { Item } from "../api/types";
import NoteEditor from "./NoteEditor";
import ListEditor from "./ListEditor";
import TableEditor from "./TableEditor";
import RoutineEditor from "./RoutineEditor";
import NoteSkeleton from "./NoteSkeleton";

export default function ItemView({
  itemId,
  onDeleted,
  onBack,
  highlightEntryId,
  highlightAnchorId,
  findText,
  onOpenItem,
}: {
  itemId: string;
  onDeleted: () => void;
  onBack: () => void;
  highlightEntryId?: string | null;
  highlightAnchorId?: string | null;
  findText?: string | null;
  onOpenItem?: (id: string) => void;
}) {
  const { data: item } = useItem(itemId);

  // Реальный найденный баг (2026-08-19, живая потеря контента при вставке
  // встроенной таблицы): useItem(itemId) иногда на один рендер отдаёт
  // undefined для ТОГО ЖЕ itemId (не смена заметки — фоновый рефетч из-за
  // WS-сигнала "items", источник до конца не локализован). !item ниже
  // раньше на этот кадр монтировал NoteSkeleton ВМЕСТО NoteEditor —
  // редактор размонтировался и терял несохранённый ввод (в частности,
  // только что вставленный узел таблицы, ещё не подтверждённый
  // автосейвом). Держим последний хороший item для ЭТОГО ЖЕ itemId и не
  // откатываемся на скелет, пока не сменился сам itemId — тот же приём,
  // что effectiveData в useItem (api/hooks.ts) уже использует для защиты
  // от чужого id, только тут ещё и от чужого "на секунду пропал".
  const lastGoodRef = useRef<{ id: string; item: Item } | null>(null);
  if (item) lastGoodRef.current = { id: itemId, item };
  const stableItem = item ?? (lastGoodRef.current?.id === itemId ? lastGoodRef.current.item : undefined);

  if (!stableItem) {
    // Списки выглядят заметно иначе (без тулбара форматирования), но
    // на этой стадии мы ещё не знаем material_type — силуэт заметки
    // достаточно близок для обоих случаев, не заводим второй skeleton
    // ради разницы, которая видна доли секунды.
    return <NoteSkeleton />;
  }

  if (stableItem.material_type === "list") {
    return (
      <ListEditor itemId={itemId} onDeleted={onDeleted} onBack={onBack} highlightEntryId={highlightEntryId} />
    );
  }
  if (stableItem.material_type === "table") {
    return <TableEditor itemId={itemId} onDeleted={onDeleted} onBack={onBack} />;
  }
  if (stableItem.material_type === "routine") {
    return <RoutineEditor itemId={itemId} onDeleted={onDeleted} onBack={onBack} />;
  }
  return (
    <NoteEditor
      itemId={itemId}
      onDeleted={onDeleted}
      onBack={onBack}
      highlightAnchorId={highlightAnchorId}
      findText={findText}
      onOpenItem={onOpenItem}
    />
  );
}

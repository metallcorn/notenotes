// Перетаскивание мышкой: заметку/список/таблицу — на папку, папку — в
// другую папку. Это надстройка для мыши поверх MoveItemModal/FolderMoveModal,
// а не замена: на телефоне HTML5-перетаскивания нет, там остаются кнопки.
//
// Свой MIME-тип, а не text/plain: иначе любой выделенный текст, брошенный
// на папку, выглядел бы как попытка переноса, а заметка, брошенная в
// редактор, вставлялась бы туда своим id.

import type { DragEvent } from "react";

const ITEM_TYPE = "application/x-notenotes-item";
const FOLDER_TYPE = "application/x-notenotes-folder";

export interface DraggedItem {
  id: string;
  space_id: string;
  folder_id: string | null;
}

export interface DraggedFolder {
  id: string;
  space_id: string;
}

export function startItemDrag(e: DragEvent, item: DraggedItem) {
  e.dataTransfer.setData(ITEM_TYPE, JSON.stringify(item));
  e.dataTransfer.effectAllowed = "move";
}

export function startFolderDrag(e: DragEvent, folder: DraggedFolder) {
  e.dataTransfer.setData(FOLDER_TYPE, JSON.stringify(folder));
  e.dataTransfer.effectAllowed = "move";
}

// Во время dragover содержимое dataTransfer браузер не отдаёт (только
// типы) — поэтому «можно ли сюда бросить» решается по типу, а
// подробности читаются уже в drop.
export function draggingSomething(e: DragEvent): "item" | "folder" | null {
  const types = Array.from(e.dataTransfer.types);
  if (types.includes(ITEM_TYPE)) return "item";
  if (types.includes(FOLDER_TYPE)) return "folder";
  return null;
}

function read<T>(e: DragEvent, type: string): T | null {
  const raw = e.dataTransfer.getData(type);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export const readDraggedItem = (e: DragEvent) => read<DraggedItem>(e, ITEM_TYPE);
export const readDraggedFolder = (e: DragEvent) => read<DraggedFolder>(e, FOLDER_TYPE);

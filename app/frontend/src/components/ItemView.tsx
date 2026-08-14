import { useItem } from "../api/hooks";
import NoteEditor from "./NoteEditor";
import ListEditor from "./ListEditor";
import NoteSkeleton from "./NoteSkeleton";

export default function ItemView({
  itemId,
  onDeleted,
  onBack,
  highlightEntryId,
  highlightAnchorId,
}: {
  itemId: string;
  onDeleted: () => void;
  onBack: () => void;
  highlightEntryId?: string | null;
  highlightAnchorId?: string | null;
}) {
  const { data: item } = useItem(itemId);

  if (!item) {
    // Списки выглядят заметно иначе (без тулбара форматирования), но
    // на этой стадии мы ещё не знаем material_type — силуэт заметки
    // достаточно близок для обоих случаев, не заводим второй skeleton
    // ради разницы, которая видна доли секунды.
    return <NoteSkeleton />;
  }

  if (item.material_type === "list") {
    return <ListEditor itemId={itemId} onDeleted={onDeleted} onBack={onBack} highlightEntryId={highlightEntryId} />;
  }
  return <NoteEditor itemId={itemId} onDeleted={onDeleted} onBack={onBack} highlightAnchorId={highlightAnchorId} />;
}

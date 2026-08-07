import { useItem } from "../api/hooks";
import NoteEditor from "./NoteEditor";
import ListEditor from "./ListEditor";
import Spinner from "./Spinner";

export default function ItemView({
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
  const { data: item } = useItem(itemId);

  if (!item) {
    return (
      <div className="flex h-full items-center justify-center text-slate-400">
        <Spinner />
      </div>
    );
  }

  if (item.material_type === "list") {
    return <ListEditor itemId={itemId} onDeleted={onDeleted} onBack={onBack} highlightEntryId={highlightEntryId} />;
  }
  return <NoteEditor itemId={itemId} onDeleted={onDeleted} onBack={onBack} />;
}

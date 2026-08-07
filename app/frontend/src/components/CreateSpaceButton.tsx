import { FormEvent, useState } from "react";
import { useCreateSpace } from "../api/hooks";
import Spinner from "./Spinner";

export default function CreateSpaceButton({ onCreated }: { onCreated: (spaceId: string) => void }) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const createSpace = useCreateSpace();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    const space = await createSpace.mutateAsync(name.trim());
    setName("");
    setAdding(false);
    onCreated(space.id);
  }

  if (!adding) {
    return (
      <button onClick={() => setAdding(true)} className="text-xs text-slate-400 hover:text-slate-700">
        + спейс
      </button>
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex gap-1">
      <input
        autoFocus
        value={name}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => !name.trim() && setAdding(false)}
        placeholder="Название"
        className="w-28 rounded border px-1.5 py-0.5 text-xs"
      />
      <button
        type="submit"
        disabled={createSpace.isPending}
        className="flex shrink-0 items-center justify-center gap-1 rounded bg-slate-900 px-2 py-0.5 text-xs text-white disabled:opacity-50"
      >
        {createSpace.isPending ? <Spinner size={12} /> : "OK"}
      </button>
    </form>
  );
}

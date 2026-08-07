import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import type { Editor, Range } from "@tiptap/core";

export interface SlashCommandItem {
  title: string;
  run: (editor: Editor, range: Range) => void;
}

export interface SlashMenuListHandle {
  onKeyDown: (props: { event: KeyboardEvent }) => boolean;
}

interface Props {
  items: SlashCommandItem[];
  command: (item: SlashCommandItem) => void;
}

const SlashMenuList = forwardRef<SlashMenuListHandle, Props>(({ items, command }, ref) => {
  const [selected, setSelected] = useState(0);

  useEffect(() => setSelected(0), [items]);

  useImperativeHandle(ref, () => ({
    onKeyDown: ({ event }) => {
      if (event.key === "ArrowDown") {
        setSelected((i) => (i + 1) % items.length);
        return true;
      }
      if (event.key === "ArrowUp") {
        setSelected((i) => (i - 1 + items.length) % items.length);
        return true;
      }
      if (event.key === "Enter") {
        if (items[selected]) command(items[selected]);
        return true;
      }
      return false;
    },
  }));

  if (items.length === 0) {
    return (
      <div className="w-56 rounded border bg-white p-2 text-xs text-slate-400 shadow-lg">Ничего не найдено</div>
    );
  }

  return (
    <div className="w-56 overflow-hidden rounded border bg-white py-1 shadow-lg">
      {items.map((item, i) => (
        <button
          key={item.title}
          onClick={() => command(item)}
          className={`block w-full px-3 py-1.5 text-left text-sm ${
            i === selected ? "bg-slate-100" : "hover:bg-slate-50"
          }`}
        >
          {item.title}
        </button>
      ))}
    </div>
  );
});

SlashMenuList.displayName = "SlashMenuList";

export default SlashMenuList;

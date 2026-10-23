import type { Editor } from "@tiptap/core";

function Btn({ onClick, children }: { onClick: () => void; children: string }) {
  return (
    <button
      onClick={onClick}
      className="rounded bg-surface px-1.5 py-0.5 text-secondary hover:bg-muted-hover"
    >
      {children}
    </button>
  );
}

export default function TableToolbar({ editor }: { editor: Editor }) {
  return (
    <div className="mx-4 mb-1 flex flex-wrap items-center gap-2 rounded-2xl bg-brand-soft px-3 py-1.5 text-xs font-bold text-brand-text">
      <span className="text-subtle">Таблица:</span>
      <div className="flex gap-0.5">
        <Btn onClick={() => editor.chain().focus().addRowBefore().run()}>Строка выше</Btn>
        <Btn onClick={() => editor.chain().focus().addRowAfter().run()}>Строка ниже</Btn>
        <Btn onClick={() => editor.chain().focus().deleteRow().run()}>Удалить строку</Btn>
      </div>
      <div className="flex gap-0.5">
        <Btn onClick={() => editor.chain().focus().addColumnBefore().run()}>Столбец слева</Btn>
        <Btn onClick={() => editor.chain().focus().addColumnAfter().run()}>Столбец справа</Btn>
        <Btn onClick={() => editor.chain().focus().deleteColumn().run()}>Удалить столбец</Btn>
      </div>
      <Btn onClick={() => editor.chain().focus().deleteTable().run()}>Удалить таблицу</Btn>
    </div>
  );
}

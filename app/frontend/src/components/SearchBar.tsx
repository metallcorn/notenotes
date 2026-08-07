export default function SearchBar({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      type="search"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder="Поиск по всем заметкам…"
      className="w-full rounded border px-3 py-1.5 text-sm"
    />
  );
}

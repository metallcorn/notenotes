import { Search, X } from "lucide-react";
import { t } from "../i18n";

export default function SearchBar({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex h-12 items-center gap-2.5 rounded-2xl bg-surface pl-4 pr-2 shadow-float focus-within:ring-2 focus-within:ring-brand/40">
      <Search size={20} className="shrink-0 text-subtle" aria-hidden="true" />
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t("search.placeholder")}
        aria-label={t("search.placeholder")}
        className="min-w-0 flex-1 bg-transparent text-[15px] text-primary outline-none placeholder:text-subtle [&::-webkit-search-cancel-button]:hidden"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Очистить"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-subtle hover:bg-muted"
        >
          <X size={16} />
        </button>
      )}
    </label>
  );
}

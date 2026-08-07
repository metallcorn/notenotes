import { useState } from "react";
import { Download } from "lucide-react";
import Spinner from "./Spinner";

export default function ExportMenu({ onExport }: { onExport: (format: "md" | "html") => Promise<void> | void }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function handle(format: "md" | "html") {
    setOpen(false);
    setBusy(true);
    try {
      await onExport(format);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        title="Экспорт"
        className="flex h-8 w-8 items-center justify-center rounded border text-slate-600 hover:bg-slate-50 disabled:opacity-50"
      >
        {busy ? <Spinner size={16} /> : <Download size={16} />}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full z-50 mt-1 w-40 rounded border bg-white py-1 shadow-lg">
            <button
              onClick={() => handle("md")}
              className="block w-full px-3 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-50"
            >
              Markdown (.md)
            </button>
            <button
              onClick={() => handle("html")}
              className="block w-full px-3 py-1.5 text-left text-sm text-slate-700 hover:bg-slate-50"
            >
              HTML (.html)
            </button>
          </div>
        </>
      )}
    </div>
  );
}

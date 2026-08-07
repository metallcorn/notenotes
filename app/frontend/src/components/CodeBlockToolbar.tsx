import type { Editor } from "@tiptap/core";

const LANGUAGES = [
  { label: "Обычный текст", value: "plaintext" },
  { label: "Bash", value: "bash" },
  { label: "JavaScript", value: "javascript" },
  { label: "TypeScript", value: "typescript" },
  { label: "Python", value: "python" },
  { label: "JSON", value: "json" },
  { label: "SQL", value: "sql" },
  { label: "YAML", value: "yaml" },
  { label: "HTML/XML", value: "xml" },
  { label: "CSS", value: "css" },
  { label: "Go", value: "go" },
  { label: "Rust", value: "rust" },
  { label: "Java", value: "java" },
  { label: "C", value: "c" },
  { label: "C++", value: "cpp" },
];

export default function CodeBlockToolbar({ editor }: { editor: Editor }) {
  const language = (editor.getAttributes("codeBlock") as { language?: string | null }).language ?? "plaintext";

  return (
    <div className="flex items-center gap-2 border-b bg-slate-50 px-3 py-1.5 text-xs">
      <span className="text-slate-500">Язык кода:</span>
      <select
        value={language}
        onChange={(e) => editor.chain().focus().updateAttributes("codeBlock", { language: e.target.value }).run()}
        className="rounded border px-1.5 py-0.5 text-xs"
      >
        {LANGUAGES.map((l) => (
          <option key={l.value} value={l.value}>
            {l.label}
          </option>
        ))}
      </select>
    </div>
  );
}

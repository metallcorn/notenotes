// Экспорт заметок и диалогов в .md/.html — оба самодостаточные файлы,
// картинки встраиваются как data: URI, а не остаются ссылками на
// /api/uploads/... (которые вне приложения ни у кого не откроются).

export function sanitizeFilename(name: string): string {
  return (name || "без названия").replace(/[/\\?%*:|"<>]/g, "-").trim().slice(0, 100) || "без названия";
}

export function downloadFile(filename: string, content: string, mime: string): void {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export async function inlineImages(text: string): Promise<string> {
  const paths = Array.from(new Set(text.match(/\/api\/uploads\/[a-zA-Z0-9-]+/g) ?? []));
  let result = text;
  for (const path of paths) {
    try {
      const res = await fetch(path, { credentials: "include" });
      if (!res.ok) continue;
      const blob = await res.blob();
      const dataUrl = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as string);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
      });
      result = result.split(path).join(dataUrl);
    } catch {
      // не удалось скачать картинку — оставляем ссылку как есть
    }
  }
  return result;
}

const HTML_DOC_STYLE = `
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; color: #0f172a; line-height: 1.6; }
  h1, h2, h3 { font-weight: 600; line-height: 1.25; margin: 1.2em 0 0.4em; }
  h1 { font-size: 1.75em; } h2 { font-size: 1.4em; } h3 { font-size: 1.15em; }
  p { margin: 0.6em 0; }
  ul, ol { margin: 0.6em 0; padding-left: 1.5em; }
  blockquote { margin: 0.8em 0; padding-left: 1em; border-left: 3px solid #cbd5e1; color: #475569; font-style: italic; }
  code { background: #f1f5f9; border-radius: 0.25rem; padding: 0.1em 0.35em; font-family: ui-monospace, monospace; font-size: 0.9em; }
  pre { background: #0f172a; color: #e2e8f0; border-radius: 0.5rem; padding: 0.9em 1.1em; overflow-x: auto; }
  pre code { background: none; padding: 0; color: inherit; }
  table { border-collapse: collapse; width: 100%; margin: 0.8em 0; }
  th, td { border: 1px solid #cbd5e1; padding: 0.4em 0.6em; text-align: left; }
  th { background: #f1f5f9; }
  a { color: #2563eb; }
  img { max-width: 100%; border-radius: 0.375rem; }
`;

export function wrapHtmlDocument(title: string, bodyHtml: string): string {
  const escapedTitle = title.replace(/</g, "&lt;");
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>${escapedTitle}</title>
<style>${HTML_DOC_STYLE}</style>
</head>
<body>
<h1>${escapedTitle}</h1>
${bodyHtml}
</body>
</html>`;
}

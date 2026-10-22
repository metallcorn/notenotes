// Построчный diff двух текстов для истории версий (макет «История
// версий», 21.10): какие строки ушли, какие пришли. Обычный LCS по
// строкам; длинные тексты обрезаются, чтобы O(n·m) не съел телефон —
// история нужна «что поменялось», а не побайтовая точность.

export type DiffLine = { kind: "same" | "add" | "del"; text: string };

const MAX_LINES = 400;

export function lineDiff(before: string, after: string): DiffLine[] {
  const a = before.split("\n").slice(0, MAX_LINES);
  const b = after.split("\n").slice(0, MAX_LINES);
  const n = a.length;
  const m = b.length;
  // dp[i][j] — длина LCS хвостов a[i:], b[j:].
  const dp: Uint16Array[] = [];
  for (let i = 0; i <= n; i++) dp.push(new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ kind: "del", text: a[i] });
      i++;
    } else {
      out.push({ kind: "add", text: b[j] });
      j++;
    }
  }
  while (i < n) out.push({ kind: "del", text: a[i++] });
  while (j < m) out.push({ kind: "add", text: b[j++] });
  return out;
}

// Схлопывает длинные куски неизменённых строк до `context` строк с каждого
// края, вставляя маркер-пропуск; пустые строки не считаются изменениями
// по смыслу, но в diff остаются как есть.
export type DiffChunk = DiffLine | { kind: "skip"; count: number };

export function collapseUnchanged(lines: DiffLine[], context = 2): DiffChunk[] {
  const out: DiffChunk[] = [];
  let run: DiffLine[] = [];
  const flush = (atEnd: boolean, atStart: boolean) => {
    if (run.length === 0) return;
    const keepHead = atStart ? 0 : context;
    const keepTail = atEnd ? 0 : context;
    if (run.length <= keepHead + keepTail + 1) {
      out.push(...run);
    } else {
      out.push(...run.slice(0, keepHead));
      out.push({ kind: "skip", count: run.length - keepHead - keepTail });
      if (keepTail > 0) out.push(...run.slice(run.length - keepTail));
    }
    run = [];
  };
  let seenChange = false;
  for (const line of lines) {
    if (line.kind === "same") {
      run.push(line);
    } else {
      flush(false, !seenChange);
      seenChange = true;
      out.push(line);
    }
  }
  flush(true, !seenChange);
  return out;
}

export function diffStats(lines: DiffLine[]): { added: number; removed: number } {
  let added = 0;
  let removed = 0;
  for (const l of lines) {
    if (l.kind === "add" && l.text.trim()) added++;
    if (l.kind === "del" && l.text.trim()) removed++;
  }
  return { added, removed };
}

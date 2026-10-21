// Человекочитаемый вес файла — реальная просьба: показать оверлеем на
// видео, сколько оно весит, до загрузки/воспроизведения.
export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return "0 Б";
  const units = ["Б", "КБ", "МБ", "ГБ"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  const digits = i === 0 || value >= 10 ? 0 : 1;
  const formatted = value.toFixed(digits).replace(/\.0$/, "");
  return `${formatted} ${units[i]}`;
}

// Человеческое время для карточек списка (макет «Заметки в папке», 21.10):
// «сегодня, 09:12», «вчера, 18:40», «19 окт», для прошлых лет — «19 окт
// 2025». Полная дата со временем остаётся в title у карточки.
export function formatRelativeDay(value: string, locale: string, now: Date = new Date()): string {
  const d = new Date(value);
  const time = d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (days === 0) return `${locale.startsWith("ru") ? "сегодня" : "today"}, ${time}`;
  if (days === 1) return `${locale.startsWith("ru") ? "вчера" : "yesterday"}, ${time}`;
  if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString(locale, { day: "numeric", month: "short" });
  return d.toLocaleDateString(locale, { day: "numeric", month: "short", year: "numeric" });
}

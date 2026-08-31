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

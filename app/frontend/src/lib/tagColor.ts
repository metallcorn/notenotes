// Цвет тега — из палитры по названию (замечание владельца 23.10: «теги
// одного цвета, с палитрой навигация лучше»). Детерминированно: один и
// тот же тег везде одного цвета, на любом устройстве, без хранения на
// сервере. Пары «подложка/текст» подобраны под светлую и тёмную тему
// (контраст ≥ 4.5:1), классы — литералы, чтобы Tailwind их собрал.
const PALETTE: { bg: string; text: string; dot: string }[] = [
  { bg: "bg-[#ECE8FF] dark:bg-[#2A2347]", text: "text-[#4A2FD6] dark:text-[#B9A8FF]", dot: "bg-[#5B3DF5]" },
  { bg: "bg-[#DCEBFF] dark:bg-[#1C2B45]", text: "text-[#1D4ED8] dark:text-[#9CC2FF]", dot: "bg-[#2F6BFF]" },
  { bg: "bg-[#E6F6DC] dark:bg-[#1F3320]", text: "text-[#1D5A12] dark:text-[#A4E29A]", dot: "bg-[#3EA33A]" },
  { bg: "bg-[#FDE9DF] dark:bg-[#3D2520]", text: "text-[#B4441B] dark:text-[#FFB08E]", dot: "bg-[#E86A3B]" },
  { bg: "bg-[#FFF1C2] dark:bg-[#3A3116]", text: "text-[#7A5500] dark:text-[#FFD773]", dot: "bg-[#E6A700]" },
  { bg: "bg-[#FFE1EE] dark:bg-[#3F2231]", text: "text-[#B0185E] dark:text-[#FFA3CB]", dot: "bg-[#E8408A]" },
  { bg: "bg-[#D9F5F0] dark:bg-[#17332E]", text: "text-[#0F6B5F] dark:text-[#8FE3D3]", dot: "bg-[#19A692]" },
  { bg: "bg-[#EAF9B8] dark:bg-[#2D3610]", text: "text-[#3F5A00] dark:text-[#D4F25A]", dot: "bg-[#B8D93A]" },
];

function hashName(name: string): number {
  let h = 2166136261;
  for (const ch of name.toLowerCase()) {
    h ^= ch.codePointAt(0) ?? 0;
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function tagColor(name: string): { bg: string; text: string; dot: string; chip: string } {
  const c = PALETTE[hashName(name) % PALETTE.length];
  return { ...c, chip: `${c.bg} ${c.text}` };
}

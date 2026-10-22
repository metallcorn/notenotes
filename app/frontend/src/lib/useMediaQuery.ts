import { useEffect, useState } from "react";

// Реактивный matchMedia. Нужен там, где телефонная и десктопная разметка
// отличаются не классами, а самим деревом (например, два разных поля
// заголовка заметки нельзя держать смонтированными одновременно — у них
// общее состояние и autoFocus). jsdom matchMedia не знает — там всегда false.
export function useMediaQuery(query: string): boolean {
  const get = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [matches, setMatches] = useState<boolean>(get);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia(query);
    const handler = () => setMatches(mq.matches);
    handler();
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [query]);
  return matches;
}

// Телефон — всё, что уже md (768px): та же граница, по которой NoteEditor
// прячет десктопные кнопки под «⋯».
export const PHONE_QUERY = "(max-width: 767px)";

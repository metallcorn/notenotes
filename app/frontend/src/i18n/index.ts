// Заготовка локализации. Интерфейс пока целиком русский; эта точка входа
// нужна, чтобы НОВЫЕ строки сразу шли через t(), а старые переносились
// сюда по мере правок, а не одним большим проходом потом.
//
// Своё, а не react-i18next: на сегодня нужен только словарь и подстановка,
// а типизированные ключи ловят забытый перевод при сборке. Сигнатура
// t(key, params) та же, что у i18next, — переезд, если понадобятся
// множественные формы и подгрузка словарей, будет механическим.
//
// Язык пока выбирается только в localStorage (переключателя в настройках
// нет): смена языка — перезагрузка страницы, без реактивности.

import { en } from "./en";
import { ru, type MessageKey } from "./ru";

export type Locale = "ru" | "en";

const DICTIONARIES: Record<Locale, Record<MessageKey, string>> = { ru, en };
const STORAGE_KEY = "notenotes.locale";

function readLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === "ru" || saved === "en") return saved;
  } catch {
    // приватный режим — язык по умолчанию
  }
  return "ru";
}

export const locale: Locale = readLocale();

// Для toLocaleString/Intl: даты и числа — в формате языка интерфейса, а
// не жёстко «ru-RU» в каждом компоненте.
export const dateLocale = locale === "en" ? "en-GB" : "ru-RU";

export function t(key: MessageKey, params?: Record<string, string | number>): string {
  const text = DICTIONARIES[locale][key] ?? ru[key];
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (m, name: string) => (name in params ? String(params[name]) : m));
}

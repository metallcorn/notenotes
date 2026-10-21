// Русский — основной язык и эталон набора ключей: en.ts обязан содержать
// ровно эти ключи, иначе не соберётся (см. тип там).
//
// Ключи плоские, «раздел.что»: искать по ним grep'ом проще, чем по
// вложенным объектам.
export const ru = {
  "nav.assistant": "Ассистент",
  "nav.activity": "Активность",
  "nav.documents": "Документы",
  "nav.trash": "Корзина",
  "nav.home": "Главная",
  "nav.notes": "Заметки",
  "nav.create": "Создать",
  "create.title": "Создать",
  "create.note": "Заметка",
  "create.list": "Список",
  "create.table": "Таблица",
  "create.ask": "Спросить ассистента",
  "create.templates": "Шаблоны",
  "create.where": "Куда",
  "create.noFolder": "Без папки",
  "create.working": "Создаём…",
  "home.night": "Доброй ночи",
  "home.morning": "Доброе утро",
  "home.day": "Добрый день",
  "home.evening": "Добрый вечер",
  "home.due": "Висит",
  "home.done": "Сделано",
  "home.tomorrow": "Завтра",
  "home.more": "ещё {n}",
  "home.spaces": "Спейсы",
  "search.placeholder": "Найти что угодно",
} as const;

export type MessageKey = keyof typeof ru;

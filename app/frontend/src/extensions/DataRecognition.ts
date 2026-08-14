import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

// Реальный запрос: автораспознавание телефонов и номеров банковских карт
// в тексте заметок. Обсудили явно PII-часть CLAUDE.md (финансовые данные
// не должны становиться ЗАМЕТНЕЕ без явного запроса) — пользователь
// explicitly выбрал "распознавать и красиво форматировать карты", отдавая
// себе отчёт в компромиссе. Важно: это ЧИСТО ВИЗУАЛЬНАЯ decoration-фича,
// как и InlineLinkFavicon/ProcessingPlaceholder рядом — ничего не уходит
// НИКУДА НОВОГО (ни в LLM/промпт ассистента, ни в отдельный индекс/
// эмбеддинги): то же самое содержимое, что и так уже лежит плейнтекстом в
// заметке и участвует в обычном полнотекстовом поиске, просто иначе
// отрисовано. Текст/markdown документа не меняется вообще.
//
// Адрес "от руки" и голый индекс сюда сознательно НЕ включены: в отличие
// от строгих форматов телефона (национальный формат, ~10-13 цифр) и карты
// (Luhn-чексумма — сильный фильтр случайных совпадений), произвольный
// адрес в свободном тексте не имеет достаточно жёсткого паттерна для
// надёжной регулярки, а голый 6-значный индекс неотличим от случайных
// чисел (цена, номер заказа) — ложных срабатываний было бы больше, чем
// пользы. Обозначено пользователю прямо, не молчаливое урезание объёма.

const PHONE_RE = /(?<!\d)(?:\+\d{1,3}[\s-]?|8[\s-]?)\(?\d{2,4}\)?(?:[\s-]?\d{2,4}){1,3}(?!\d)/g;
const CARD_RE = /(?<!\d)(?:\d[ -]?){13,19}(?!\d)/g;

function luhnValid(digits: string): boolean {
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    let n = parseInt(digits[i], 10);
    if (alt) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
    alt = !alt;
  }
  return sum % 10 === 0;
}

function findPhoneRanges(text: string): Array<{ from: number; to: number }> {
  const ranges: Array<{ from: number; to: number }> = [];
  for (const m of text.matchAll(PHONE_RE)) {
    const digits = m[0].replace(/\D/g, "");
    // Отсекаем слишком короткие/длинные совпадения — регулярка выше
    // допускает от 1 до 3 групп после кода, реальный телефон это не любая
    // такая последовательность.
    if (digits.length < 10 || digits.length > 13) continue;
    ranges.push({ from: m.index!, to: m.index! + m[0].length });
  }
  return ranges;
}

function findCardRanges(text: string): Array<{ from: number; to: number; digits: string }> {
  const ranges: Array<{ from: number; to: number; digits: string }> = [];
  for (const m of text.matchAll(CARD_RE)) {
    const digits = m[0].replace(/\D/g, "");
    if (digits.length < 13 || digits.length > 19) continue;
    if (!luhnValid(digits)) continue;
    ranges.push({ from: m.index!, to: m.index! + m[0].length, digits });
  }
  return ranges;
}

export const DataRecognition = Extension.create({
  name: "dataRecognition",

  addProseMirrorPlugins() {
    const key = new PluginKey("dataRecognition");
    return [
      new Plugin({
        key,
        props: {
          decorations(state) {
            const decorations: Decoration[] = [];

            state.doc.descendants((node, pos) => {
              if (!node.isText || !node.text) return;
              // Не трогаем текст ссылок — номер в составе URL (например,
              // трекинг-номер посылки) не телефон и не карта.
              if (node.marks.some((m) => m.type.name === "link")) return;

              for (const { from, to } of findPhoneRanges(node.text)) {
                decorations.push(
                  Decoration.widget(
                    pos + from,
                    () => {
                      const a = document.createElement("a");
                      a.href = `tel:${node.text!.slice(from, to).replace(/[^\d+]/g, "")}`;
                      a.className = "recognized-phone-icon";
                      a.title = "Позвонить";
                      a.textContent = "📞";
                      a.contentEditable = "false";
                      return a;
                    },
                    { side: -1 },
                  ),
                );
              }

              for (const { from, to } of findCardRanges(node.text)) {
                decorations.push(Decoration.inline(pos + from, pos + to, { class: "recognized-card" }));
              }
            });

            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});

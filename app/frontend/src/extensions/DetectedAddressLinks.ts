import { Extension } from "@tiptap/core";
import type { Node as PMNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

// Реальная жалоба: адрес в заметке (в т.ч. созданной ассистентом) не
// становится кликабельной ссылкой на карту. Свободный текст адреса — не
// строгий формат вроде телефона/номера карты (DataRecognition.ts рядом,
// там регулярка + Luhn), надёжной регулярки для произвольного адреса нет —
// поэтому источник совпадений здесь не паттерн, а сам LLM (app/autotag.py,
// тот же комбинированный вызов, что и у тегов/дат). Фронт только ищет
// присланный текст в документе и подсвечивает — если не нашёл (заметку
// успели отредактировать после того, как эта версия текста была
// проанализирована) — просто не подсвечивает, тихо, без ошибок.
//
// Ищем по абзацу целиком, а не по одному текстовому узлу: LLM видит
// Markdown-исходник, и адрес у него может быть жирным («**ul. X 1**»),
// разбит переносом строки на улицу и название места или склеен с
// соседним текстом. В документе это разные узлы (жирный — отдельный
// текстовый узел, перенос — hardBreak), поэтому сравнение «узел содержит
// строку» молча проваливалось (реальный случай: адрес из пересланного
// сообщения Telegram без значка карты). Сравниваем нормализованно:
// Markdown-разметка снята, любые пробелы и переносы — один пробел.
//
// editor.storage.detectedAddressLinks.addresses — не .configure(): item
// меняется при переключении заметки, а конфиг расширений схватывается
// один раз при создании editor-инстанса (тот же приём и та же причина,
// что у editor.storage.ticketAttachment, см. TicketAttachment.ts).
export interface DetectedAddress {
  text: string;
  query: string;
}

const MARKDOWN_MARKS_RE = /[*_`~]+/g;

function normalizeSpace(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

// Варианты написания адреса, которые пробуем по очереди: как прислал LLM
// (на случай, если звёздочки лежат в тексте буквально) и без разметки.
function candidates(text: string): string[] {
  const raw = normalizeSpace(text);
  const bare = normalizeSpace(text.replace(MARKDOWN_MARKS_RE, ""));
  return raw && raw !== bare ? [raw, bare] : [raw || bare];
}

// Текст абзаца с картой «символ → позиция в документе». Пробельные
// последовательности (включая hardBreak) схлопнуты в один пробел, чтобы
// совпадать с normalizeSpace() у искомой строки.
function blockText(block: PMNode, blockPos: number): { text: string; positions: number[] } {
  let text = "";
  const positions: number[] = [];
  let pendingSpace = false;
  const push = (ch: string, pos: number) => {
    if (/\s/.test(ch)) {
      pendingSpace = text.length > 0;
      return;
    }
    if (pendingSpace) {
      text += " ";
      positions.push(pos);
      pendingSpace = false;
    }
    text += ch;
    positions.push(pos);
  };
  block.forEach((child, offset) => {
    const base = blockPos + 1 + offset;
    if (child.isText && child.text) {
      for (let i = 0; i < child.text.length; i += 1) push(child.text[i], base + i);
    } else if (child.type.name === "hardBreak") {
      push(" ", base);
    } else {
      push("￼", base);
    }
  });
  return { text, positions };
}

/** Позиции в документе, где начинается каждое вхождение каждого адреса,
 *  вместе с запросом для карты. Чистая функция — проверяется тестом. */
export function findAddressPositions(doc: PMNode, addresses: DetectedAddress[]): { pos: number; query: string }[] {
  const found: { pos: number; query: string }[] = [];
  if (!addresses.length) return found;
  const prepared = addresses
    .filter((a) => a.text)
    .map((a) => ({ query: a.query, variants: candidates(a.text).filter(Boolean) }));
  doc.descendants((node, pos) => {
    if (!node.isTextblock) return true;
    const { text, positions } = blockText(node, pos);
    if (!text) return false;
    for (const { query, variants } of prepared) {
      for (const needle of variants) {
        let idx = text.indexOf(needle);
        if (idx === -1) continue;
        while (idx !== -1) {
          found.push({ pos: positions[idx], query });
          idx = text.indexOf(needle, idx + needle.length);
        }
        break;
      }
    }
    return false;
  });
  return found;
}

export const DetectedAddressLinks = Extension.create({
  name: "detectedAddressLinks",

  addStorage() {
    return { addresses: [] as DetectedAddress[] };
  },

  addProseMirrorPlugins() {
    const key = new PluginKey("detectedAddressLinks");
    const extensionThis = this;
    return [
      new Plugin({
        key,
        props: {
          decorations(state) {
            const addresses = extensionThis.storage.addresses as DetectedAddress[];
            if (!addresses.length) return null;

            const decorations = findAddressPositions(state.doc, addresses).map(({ pos, query }) =>
              Decoration.widget(
                pos,
                () => {
                  const a = document.createElement("a");
                  a.href = `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`;
                  a.target = "_blank";
                  a.rel = "noopener noreferrer";
                  a.className = "recognized-address-icon";
                  a.title = "Открыть на карте";
                  a.textContent = "📍";
                  a.contentEditable = "false";
                  return a;
                },
                { side: -1 },
              ),
            );

            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});

import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

// Реальная жалоба: адрес в заметке (в т.ч. созданной ассистентом) не
// становится кликабельной ссылкой на карту. Свободный текст адреса — не
// строгий формат вроде телефона/номера карты (DataRecognition.ts рядом,
// там регулярка + Luhn), надёжной регулярки для произвольного адреса нет —
// поэтому источник совпадений здесь не паттерн, а сам LLM (app/autotag.py,
// тот же комбинированный вызов, что и у тегов/дат). Фронт только ищет
// ДОСЛОВНО присланный текст в документе и подсвечивает — если не нашёл
// (заметку успели отредактировать после того, как эта версия текста была
// проанализирована) — просто не подсвечивает, тихо, без ошибок.
//
// editor.storage.detectedAddressLinks.addresses — не .configure(): item
// меняется при переключении заметки, а конфиг расширений схватывается
// один раз при создании editor-инстанса (тот же приём и та же причина,
// что у editor.storage.ticketAttachment, см. TicketAttachment.ts).
export interface DetectedAddress {
  text: string;
  query: string;
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

            const decorations: Decoration[] = [];
            state.doc.descendants((node, pos) => {
              if (!node.isText || !node.text) return;
              for (const { text, query } of addresses) {
                if (!text) continue;
                let idx = node.text.indexOf(text);
                while (idx !== -1) {
                  const from = pos + idx;
                  decorations.push(
                    Decoration.widget(
                      from,
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
                  idx = node.text.indexOf(text, idx + text.length);
                }
              }
            });

            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});

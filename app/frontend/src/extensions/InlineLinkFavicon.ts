import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

// Реальная жалоба: ссылки, встроенные ВНУТРИ строки описания ("🔗 Сайт
// фестиваля: [readyfest.pl](url)") — не "одна ссылка на строке" (см.
// useNodeViewPreview.ts — для тех уже есть богатая карточка/пачка), а
// именно часть предложения — никак визуально не выделялись, обычный синий
// подчёркнутый текст, будь то написано ассистентом или руками. Пользователь
// явно выбрал (не гадаю): маленький бейдж с иконкой сайта ПРЯМО в строке,
// не большая карточка. Чисто визуальная ProseMirror-декорация — вставляет
// значок сайта перед текстом ссылки, не меняет ни документ, ни markdown-
// сериализацию.
//
// favicon.ico по хосту напрямую (без похода на бэкенд/useLinkPreview) —
// тот же fallback-путь, что уже использует backend, когда на странице нет
// <link rel="icon"> (link_preview.py: urljoin(final_url, "/favicon.ico")).
// Картинку грузит сам браузер: не нужен async-стейт внутри декорации,
// которая должна быть чистой синхронной функцией от состояния документа.
export const InlineLinkFavicon = Extension.create({
  name: "inlineLinkFavicon",

  addProseMirrorPlugins() {
    const key = new PluginKey("inlineLinkFavicon");
    return [
      new Plugin({
        key,
        props: {
          decorations(state) {
            const decorations: Decoration[] = [];
            let prevHref: string | null = null;

            state.doc.descendants((node, pos) => {
              if (!node.isText) {
                prevHref = null;
                return;
              }
              const linkMark = node.marks.find((m) => m.type.name === "link");
              const href = (linkMark?.attrs.href as string | undefined) ?? null;

              if (href && href !== prevHref) {
                let hostname: string | null = null;
                try {
                  const parsed = new URL(href);
                  // Ссылка на само приложение (например, ассистент оставил
                  // ссылку на другую заметку) — бейдж с иконкой сайта тут
                  // не имеет смысла, это не внешний сайт.
                  if (parsed.hostname !== window.location.hostname) hostname = parsed.hostname;
                } catch {
                  hostname = null;
                }
                if (hostname) {
                  const iconHostname = hostname;
                  decorations.push(
                    Decoration.widget(
                      pos,
                      () => {
                        const img = document.createElement("img");
                        img.src = `https://${iconHostname}/favicon.ico`;
                        img.alt = "";
                        img.className = "inline-link-favicon";
                        img.onerror = () => img.remove();
                        return img;
                      },
                      { side: -1 },
                    ),
                  );
                }
              }
              prevHref = href;
            });

            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});

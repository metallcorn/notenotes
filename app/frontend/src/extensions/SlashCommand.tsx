import { Extension } from "@tiptap/core";
import Suggestion from "@tiptap/suggestion";
import { ReactRenderer } from "@tiptap/react";
import SlashMenuList, { type SlashCommandItem, type SlashMenuListHandle } from "../components/SlashMenuList";

function buildItems(onInsertImage: () => void, onCreateReminder: (pos: number) => void): SlashCommandItem[] {
  return [
    {
      title: "Заголовок 1",
      aliases: ["heading", "h1", "title"],
      run: (editor, range) => editor.chain().focus().deleteRange(range).setNode("heading", { level: 1 }).run(),
    },
    {
      title: "Заголовок 2",
      aliases: ["heading", "h2"],
      run: (editor, range) => editor.chain().focus().deleteRange(range).setNode("heading", { level: 2 }).run(),
    },
    {
      title: "Заголовок 3",
      aliases: ["heading", "h3"],
      run: (editor, range) => editor.chain().focus().deleteRange(range).setNode("heading", { level: 3 }).run(),
    },
    {
      title: "Маркированный список",
      aliases: ["list", "bullet", "ul"],
      run: (editor, range) => editor.chain().focus().deleteRange(range).toggleBulletList().run(),
    },
    {
      title: "Нумерованный список",
      aliases: ["list", "numbered", "ordered", "ol"],
      run: (editor, range) => editor.chain().focus().deleteRange(range).toggleOrderedList().run(),
    },
    {
      title: "Цитата",
      aliases: ["quote", "blockquote"],
      run: (editor, range) => editor.chain().focus().deleteRange(range).toggleBlockquote().run(),
    },
    {
      title: "Блок кода",
      aliases: ["code", "codeblock"],
      run: (editor, range) => editor.chain().focus().deleteRange(range).toggleCodeBlock().run(),
    },
    {
      title: "Разделитель",
      aliases: ["divider", "hr", "line", "separator"],
      run: (editor, range) => editor.chain().focus().deleteRange(range).setHorizontalRule().run(),
    },
    {
      title: "Отступ",
      aliases: ["spacer", "space", "gap"],
      // В отличие от нескольких пустых абзацев подряд (которые схлопываются
      // в один при сохранении — Markdown не различает несколько пустых
      // строк и одну), это отдельный блочный узел — можно ставить сколько
      // угодно подряд, каждый переживёт сохранение и переоткрытие.
      // Вставляем сразу с пустым абзацем следом и переводим туда курсор —
      // иначе после вставки атом остаётся NodeSelection'ом, и следующая же
      // напечатанная буква по умолчанию поведению ProseMirror заменяет
      // собой сам узел вместо того, чтобы просто продолжить текст.
      run: (editor, range) =>
        editor.chain().focus().deleteRange(range).insertContent([{ type: "spacer" }, { type: "paragraph" }]).run(),
    },
    {
      title: "Картинка",
      aliases: ["image", "photo", "picture", "img"],
      run: (editor, range) => {
        editor.chain().focus().deleteRange(range).run();
        onInsertImage();
      },
    },
    {
      title: "Напоминание",
      // Реальный запрос: "/notify — открывается форма, выбираешь дату/
      // время, можешь написать текст" — тот же приём, что "Картинка"
      // выше: слэш-команда не вставляет узел сама, а открывает внешний
      // UI (ReminderModal.tsx через NoteEditor.tsx), который уже умеет
      // создать привязанное к этой заметке напоминание. aliases — не
      // полноценная локализация (текст пункта всё равно на русском, её в
      // приложении просто нет нигде), только слова для поиска: набираешь
      // /notify, находишь тот же пункт, что и по /напом.
      aliases: ["notify", "reminder", "remind", "notification", "alarm"],
      run: (editor, range) => {
        editor.chain().focus().deleteRange(range).run();
        // Позиция ПОСЛЕ deleteRange — то самое место, куда позже встанет
        // якорь-иконка (ReminderAnchor.ts), когда напоминание реально
        // создастся: "я ставлю не просто так, а как якорь, чтобы вернуться
        // именно к этой строке" — реальная жалоба, курсор здесь и сейчас
        // единственный момент, когда мы точно знаем нужную позицию.
        onCreateReminder(editor.state.selection.from);
      },
    },
  ];
}

export interface SlashCommandOptions {
  onInsertImage: () => void;
  onCreateReminder: (pos: number) => void;
}

export const SlashCommand = Extension.create<SlashCommandOptions>({
  name: "slashCommand",

  addOptions() {
    return {
      onInsertImage: () => {},
      onCreateReminder: () => {},
    };
  },

  addProseMirrorPlugins() {
    const items = buildItems(this.options.onInsertImage, this.options.onCreateReminder);

    return [
      Suggestion<SlashCommandItem, SlashCommandItem>({
        editor: this.editor,
        char: "/",
        startOfLine: false,
        items: ({ query }) => {
          const q = query.toLowerCase();
          // Реальный найденный баг: aliases добавили в данные пунктов, но
          // забыли подключить сюда — /notify и все остальные английские
          // алиасы физически не работали, фильтр смотрел только на title.
          return items
            .filter((i) => i.title.toLowerCase().includes(q) || i.aliases?.some((a) => a.includes(q)))
            .slice(0, 10);
        },
        command: ({ editor, range, props }) => {
          props.run(editor, range);
        },
        render: () => {
          let component: ReactRenderer<SlashMenuListHandle> | null = null;
          let popup: HTMLDivElement | null = null;

          function position(rect: DOMRect | null | undefined) {
            if (!popup || !rect) return;
            popup.style.left = `${rect.left}px`;
            popup.style.top = `${rect.bottom + 6}px`;
          }

          return {
            onStart: (props) => {
              component = new ReactRenderer(SlashMenuList, { props, editor: props.editor });
              popup = document.createElement("div");
              popup.style.position = "fixed";
              popup.style.zIndex = "50";
              document.body.appendChild(popup);
              popup.appendChild(component.element);
              position(props.clientRect?.());
            },
            onUpdate: (props) => {
              component?.updateProps(props);
              position(props.clientRect?.());
            },
            onKeyDown: (props) => {
              if (props.event.key === "Escape") {
                popup?.remove();
                return true;
              }
              return component?.ref?.onKeyDown({ event: props.event }) ?? false;
            },
            onExit: () => {
              popup?.remove();
              popup = null;
              component?.destroy();
              component = null;
            },
          };
        },
      }),
    ];
  },
});

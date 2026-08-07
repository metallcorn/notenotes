import { Extension } from "@tiptap/core";
import Suggestion from "@tiptap/suggestion";
import { ReactRenderer } from "@tiptap/react";
import SlashMenuList, { type SlashCommandItem, type SlashMenuListHandle } from "../components/SlashMenuList";

function buildItems(onInsertImage: () => void): SlashCommandItem[] {
  return [
    {
      title: "Заголовок 1",
      run: (editor, range) => editor.chain().focus().deleteRange(range).setNode("heading", { level: 1 }).run(),
    },
    {
      title: "Заголовок 2",
      run: (editor, range) => editor.chain().focus().deleteRange(range).setNode("heading", { level: 2 }).run(),
    },
    {
      title: "Заголовок 3",
      run: (editor, range) => editor.chain().focus().deleteRange(range).setNode("heading", { level: 3 }).run(),
    },
    {
      title: "Маркированный список",
      run: (editor, range) => editor.chain().focus().deleteRange(range).toggleBulletList().run(),
    },
    {
      title: "Нумерованный список",
      run: (editor, range) => editor.chain().focus().deleteRange(range).toggleOrderedList().run(),
    },
    {
      title: "Цитата",
      run: (editor, range) => editor.chain().focus().deleteRange(range).toggleBlockquote().run(),
    },
    {
      title: "Блок кода",
      run: (editor, range) => editor.chain().focus().deleteRange(range).toggleCodeBlock().run(),
    },
    {
      title: "Разделитель",
      run: (editor, range) => editor.chain().focus().deleteRange(range).setHorizontalRule().run(),
    },
    {
      title: "Картинка",
      run: (editor, range) => {
        editor.chain().focus().deleteRange(range).run();
        onInsertImage();
      },
    },
  ];
}

export interface SlashCommandOptions {
  onInsertImage: () => void;
}

export const SlashCommand = Extension.create<SlashCommandOptions>({
  name: "slashCommand",

  addOptions() {
    return {
      onInsertImage: () => {},
    };
  },

  addProseMirrorPlugins() {
    const items = buildItems(this.options.onInsertImage);

    return [
      Suggestion<SlashCommandItem, SlashCommandItem>({
        editor: this.editor,
        char: "/",
        startOfLine: false,
        items: ({ query }) => items.filter((i) => i.title.toLowerCase().includes(query.toLowerCase())).slice(0, 10),
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

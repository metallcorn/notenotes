import { Extension } from "@tiptap/core";
import { PluginKey } from "@tiptap/pm/state";
import Suggestion from "@tiptap/suggestion";
import { ReactRenderer } from "@tiptap/react";
import NoteLinkSuggestionList, { type NoteLinkSuggestionListHandle } from "../components/NoteLinkSuggestionList";
import type { ItemTitleSearchResult } from "../api/types";

// Триггер [[ — тот же паттерн, что / у SlashCommand.tsx (Suggestion из
// @tiptap/suggestion), только двухсимвольный char (поддерживается —
// findSuggestionMatch экранирует char целиком и режет query по его длине,
// не привязан к одному символу) и живой поиск вместо статичного списка
// (NoteLinkSuggestionList сама ходит за данными по query).
//
// Реальный найденный баг (живой краш редактора при открытии ЛЮБОЙ заметки):
// Suggestion() без явного pluginKey использует один и тот же дефолтный ключ
// "suggestion$" — SlashCommand.tsx уже регистрирует такой же плагин под
// умолчанием, и ProseMirror отказывался добавлять второй плагин с тем же
// ключом ("Adding different instances of a keyed plugin"), роняя весь
// редактор ещё на этапе createEditor. Свой уникальный pluginKey решает это.
const noteLinkSuggestionKey = new PluginKey("noteLinkSuggestion");

export const NoteLinkSuggestion = Extension.create({
  name: "noteLinkSuggestion",

  addProseMirrorPlugins() {
    return [
      Suggestion<ItemTitleSearchResult, ItemTitleSearchResult>({
        pluginKey: noteLinkSuggestionKey,
        editor: this.editor,
        char: "[[",
        startOfLine: false,
        items: () => [],
        command: ({ editor, range, props }) => {
          editor
            .chain()
            .focus()
            .deleteRange(range)
            .insertContent({ type: "noteLink", attrs: { itemId: props.id, title: props.title } })
            .insertContent(" ")
            .run();
        },
        render: () => {
          let component: ReactRenderer<NoteLinkSuggestionListHandle> | null = null;
          let popup: HTMLDivElement | null = null;

          function position(rect: DOMRect | null | undefined) {
            if (!popup || !rect) return;
            popup.style.left = `${rect.left}px`;
            popup.style.top = `${rect.bottom + 6}px`;
          }

          return {
            onStart: (props) => {
              component = new ReactRenderer(NoteLinkSuggestionList, { props, editor: props.editor });
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

import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { describe, expect, it } from "vitest";
import { NoteLink } from "./NoteLink";
import { NoteLinkSuggestion } from "./NoteLinkSuggestion";
import { SlashCommand } from "./SlashCommand";

// Реальный найденный краш (живые данные, ErrorBoundary): "Adding different
// instances of a keyed plugin (suggestion$)" — SlashCommand (char: "/") и
// NoteLinkSuggestion (char: "[[") оба используют @tiptap/suggestion, и без
// явного pluginKey у второго ProseMirror отказывался собирать редактор
// вообще — редактор падал на КАЖДОЙ заметке, не только с новым узлом.
// Единственный надёжный способ проверить это — реально создать Editor с
// обоими расширениями сразу и убедиться, что createEditor не бросает.
describe("SlashCommand + NoteLinkSuggestion — совместная регистрация", () => {
  it("не падает при создании редактора с обоими Suggestion-плагинами одновременно", () => {
    expect(() => {
      const editor = new Editor({
        extensions: [
          StarterKit,
          NoteLink,
          SlashCommand.configure({ onInsertImage: () => {}, onCreateReminder: () => {}, onInsertTable: () => {} }),
          NoteLinkSuggestion,
        ],
        content: "<p>текст</p>",
      });
      editor.destroy();
    }).not.toThrow();
  });
});

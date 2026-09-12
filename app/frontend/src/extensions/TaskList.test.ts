import { Editor } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import TaskItem from "@tiptap/extension-task-item";
import TaskList from "@tiptap/extension-task-list";
import { Markdown } from "tiptap-markdown";
import { describe, expect, it } from "vitest";

/**
 * Чек-листы «- [ ] пункт» — круговой путь Markdown → редактор → Markdown.
 *
 * Живой случай: внешний ассистент через MCP создал заметку с 14 пунктами
 * в стандартном Markdown, а редактор показал их обычным списком с «[ ]»
 * в тексте. tiptap-markdown умел это с самого начала — не хватало только
 * самих узлов TaskList/TaskItem в редакторе.
 */
function make(content: string) {
  return new Editor({
    extensions: [
      StarterKit,
      TaskList,
      TaskItem.configure({ nested: true }),
      // Те же опции, что в NoteEditor: иначе тест проверял бы не то, чем
      // пользуются.
      Markdown.configure({ html: true, transformPastedText: true }),
    ],
    content,
  });
}

describe("чек-листы", () => {
  it("«- [ ]» становится чекбоксом, а не текстом в скобках", () => {
    const editor = make("- [ ] Собрать документы\n- [x] Найти переводчика");
    const html = editor.getHTML();

    expect(html).toContain('data-type="taskList"');
    expect(html).toContain('data-checked="false"');
    expect(html).toContain('data-checked="true"');
    // Скобки не должны остаться видимым текстом.
    expect(html).not.toContain("[ ]");
    expect(html).not.toContain("[x]");
  });

  it("сохраняется обратно в Markdown с чекбоксами", () => {
    // Формат хранения — всегда Markdown (CLAUDE.md). Если редактор
    // переписал бы чек-лист во что-то своё, заметка сломалась бы для
    // ассистента, бота и экспорта. Пустая строка между пунктами — это
    // «loose list», тот же Markdown по смыслу; так же сериализуются и
    // обычные списки в этом редакторе.
    const editor = make("- [ ] Первое\n- [x] Второе");
    const out = editor.storage.markdown.getMarkdown();

    expect(out).toMatch(/- \[ \] Первое\n+- \[x\] Второе/);
    expect(out).not.toContain("taskList");
  });

  it("отметка галочкой меняет Markdown", () => {
    const editor = make("- [ ] Дело");
    editor.commands.toggleTaskList; // сам список уже task list
    // Ставим checked через транзакцию на узле.
    editor.commands.command(({ tr, state }) => {
      state.doc.descendants((node, pos) => {
        if (node.type.name === "taskItem") tr.setNodeMarkup(pos, undefined, { ...node.attrs, checked: true });
      });
      return true;
    });

    expect(editor.storage.markdown.getMarkdown().trim()).toBe("- [x] Дело");
  });

  it("обычный список остаётся обычным", () => {
    // Расширение не должно превращать «- пункт» в чекбоксы.
    const editor = make("- Просто пункт");
    expect(editor.getHTML()).not.toContain("taskList");
  });
});

import { Editor, type AnyExtension } from "@tiptap/core";
import { EditorState, Plugin, PluginKey } from "@tiptap/pm/state";
import { keydownHandler } from "@tiptap/pm/keymap";
import {
  ySyncPlugin,
  ySyncPluginKey,
  yCursorPlugin,
  yCursorPluginKey,
  yUndoPlugin,
  yUndoPluginKey,
  undo as yUndo,
  redo as yRedo,
  initProseMirrorDoc,
  prosemirrorToYXmlFragment,
} from "y-prosemirror";
import type { CollabProvider } from "./collabProvider";

// Единственный стабильный экземпляр редактора переиспользуется для ВСЕХ
// заметок (NoteEditor.tsx, useMemo([]) — есть отдельный, задокументированный
// в коде повод так делать: пересоздание редактора/массива extensions на
// каждый рендер раньше роняло React-NodeView'ы, .destroy() на null).
// @tiptap/extension-collaboration подразумевает один Y.Doc на весь срок
// жизни ОДНОГО редактора — не подходит напрямую. Вместо готовой обёртки
// используем низкоуровневые функции y-prosemirror и подменяем доку+плагины
// синхронизации при переключении заметок через editor.view.updateState —
// тот же механизм, которым пользуются editor.registerPlugin/unregisterPlugin
// внутри, но нам нужно менять doc И плагины одним атомарным шагом (иначе
// возможен короткий момент, когда ySyncPlugin уже привязан, а doc ещё не
// выведен из Yjs-фрагмента — в точности то, чего избегает штатный паттерн
// y-prosemirror: initProseMirrorDoc → EditorState.create → и только потом
// плагин).
const collabUndoKeymapKey = new PluginKey("collabUndoOverride");

// PluginKey/Plugin хранят внутреннюю строку .key ("y-sync$" и т.п.) в
// рантайме, но публичные типы prosemirror-state её не объявляют —
// единственный надёжный способ сравнить "этот плагин создан этим ключом"
// без структурного различия версий (getState требует полноценный
// EditorState, а не голый список плагинов).
function keyString(k: PluginKey | Plugin): string {
  return (k as unknown as { key: string }).key;
}

const MANAGED_KEYS = [keyString(ySyncPluginKey), keyString(yCursorPluginKey), keyString(yUndoPluginKey), keyString(collabUndoKeymapKey)];

function isManagedCollabPlugin(plugin: Plugin): boolean {
  return MANAGED_KEYS.includes(keyString(plugin));
}

// y-prosemirror по умолчанию рисует курсор/выделение чужими цветами очень
// ярко (defaultSelectionBuilder — заливка с alpha 0x70, почти непрозрачная)
// — реальная жалоба: "не оч красиво, не в общем дизайне продукта". Вместо
// этого: тонкая цветная вертикальная черта с маленькой скруглённой
// подписью-именем сверху (тот же язык, что уже используют тултипы карточек
// в приложении), и полупрозрачная (не кричащая) заливка выделения.
function buildCollabCursor(user: { name: string; color: string }): HTMLElement {
  const cursor = document.createElement("span");
  cursor.style.borderLeft = `2px solid ${user.color}`;
  cursor.style.marginLeft = "-1px";
  cursor.style.marginRight = "-1px";
  cursor.style.position = "relative";
  cursor.style.wordBreak = "normal";
  cursor.style.pointerEvents = "none";

  const label = document.createElement("span");
  label.textContent = user.name;
  label.contentEditable = "false";
  label.style.position = "absolute";
  label.style.top = "-1.35em";
  label.style.left = "-2px";
  label.style.whiteSpace = "nowrap";
  label.style.userSelect = "none";
  label.style.pointerEvents = "none";
  label.style.fontSize = "11px";
  label.style.lineHeight = "1.4";
  label.style.padding = "0 5px";
  label.style.borderRadius = "4px";
  label.style.color = "#fff";
  label.style.background = user.color;
  cursor.appendChild(label);
  return cursor;
}

function buildCollabSelection(user: { color: string }): { style: string; class: string } {
  // "22" — hex-альфа ~13% (не 70/44%, как в дефолте y-prosemirror) —
  // видно, чей это выбор, не мешая читать сам текст.
  return { style: `background-color: ${user.color}22`, class: "collab-selection" };
}

export async function attachCollab(
  editor: Editor,
  extensions: AnyExtension[],
  provider: CollabProvider,
  seedMarkdown: string,
  user: { name: string; color: string },
): Promise<void> {
  const fragment = provider.doc.getXmlFragment("prosemirror");

  await provider.connect(() => {
    // Мы — "сеятель" совсем свежей комнаты (см. app/collab.py): наполняем
    // фрагмент текущим содержимым заметки. Одноразовый невидимый редактор
    // с ТЕМИ ЖЕ extensions (переданы явно вызывающим кодом — тот же
    // стабильный массив, из которого построен основной editor) — только
    // чтобы распарсить markdown в ProseMirror-узел тем же способом, каким
    // это уже делает обычная загрузка заметки (editor.commands.setContent);
    // сразу уничтожается, на экране никогда не появляется.
    //
    // Реальный найденный баг (2026-08-19, дважды за один день, две разные
    // формы): здесь раньше стояла эвристика isDocMeaningfullyEmpty,
    // угадывавшая "пусто ли это" по СТРУКТУРЕ распарсенного документа
    // (childCount/textContent) — сначала не считала контентом заметку из
    // одного атом-узла (картинка/встроенная таблица/вложение/билет) без
    // единого символа текста, потом (после первого фикса) всё равно
    // ошиблась на заметке "пустой абзац + картинка", оставшейся после
    // ручного удаления текста. Каждый раз итог один: при пересидинге
    // комнаты (обрыв связи, invalidate_room от фонового воркера/ассистента)
    // реальный контент такой заметки не попадал в Yjs вообще, и следующий
    // же автосейв стирал его на сервере тоже — угадывать по структуре
    // документа принципиально ненадёжно, у атом-узлов бесконечно много
    // комбинаций с текстом/друг с другом. Полагаемся вместо этого на
    // ИСХОДНУЮ СТРОКУ: "нечего сеять" — только когда сам markdown с сервера
    // (не его распарсенная структура) пуст или состоит из пробельных
    // символов. Любой непустой markdown сеется как есть, без исключений.
    if (!seedMarkdown.trim()) {
      provider.markSeedComplete();
      return;
    }
    const temp = new Editor({
      extensions,
      content: seedMarkdown,
      editable: false,
    });
    const parsedDoc = temp.state.doc;
    temp.destroy();
    prosemirrorToYXmlFragment(parsedDoc, fragment);
  });

  const { doc, mapping } = initProseMirrorDoc(fragment, editor.schema);
  const preserved = editor.state.plugins.filter((p) => !isManagedCollabPlugin(p));

  // Перехват Mod-z/Mod-y ДО штатной истории StarterKit (её плагин остаётся
  // в preserved нетронутым) — подставляем свой keymap-плагин ПЕРВЫМ в
  // списке: ProseMirror пробует обработчики по порядку плагинов и
  // останавливается на первом, кто вернул true.
  const undoKeymapPlugin = new Plugin({
    key: collabUndoKeymapKey,
    props: {
      handleKeyDown: keydownHandler({
        "Mod-z": yUndo,
        "Mod-y": yRedo,
        "Mod-Shift-z": yRedo,
      }),
    },
  });

  const plugins = [
    undoKeymapPlugin,
    ySyncPlugin(fragment, { mapping }),
    yCursorPlugin(provider.awareness, { cursorBuilder: buildCollabCursor, selectionBuilder: buildCollabSelection }),
    yUndoPlugin(),
    ...preserved,
  ];

  editor.view.updateState(EditorState.create({ schema: editor.schema, doc, plugins }));
  provider.awareness.setLocalStateField("user", user);
}

// Снимает плагины синхронизации и закрывает соединение — содержимое
// редактора после этого остаётся как есть (последнее, что успело
// прилететь по Yjs); вызывающий код (NoteEditor.tsx) сразу следом сам
// подставляет содержимое новой заметки обычным setContent, тем же путём,
// что и для не-совместных заметок.
export function detachCollab(editor: Editor, provider: CollabProvider | null): void {
  if (provider) provider.disconnect();
  const preserved = editor.state.plugins.filter((p) => !isManagedCollabPlugin(p));
  editor.view.updateState(
    EditorState.create({ schema: editor.schema, doc: editor.state.doc, selection: editor.state.selection, plugins: preserved }),
  );
}

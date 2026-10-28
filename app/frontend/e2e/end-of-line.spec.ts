import { test, expect, type Page } from "@playwright/test";

// Жалоба 28.10: «ставлю курсор в конец строки — не печатает; надо
// кликнуть выше, что-то напечатать, и только потом конец строки
// оживает». Причина и починка — lib/editorSelection.ts: заметка
// начинается с линии, ProseMirror держит на ней невидимое выделение
// узла, Chrome на клик у жёсткого переноса курсор не двигает, набранное
// заменяло линию наверху. Данные вымышленные, структура — как у живой
// заметки: жёсткие переносы (`\`), пустой заголовок, карточка ссылки,
// горизонтальные линии.

const CONTENT = [
  "---",
  "",
  "### **Документы Яна Ковальского:**",
  "",
  "#### **1. Паспорт**",
  "",
  "Выдан в г. Варшава, ул. Пшикладова 1",
  "",
  "**Номер № 12345678**",
  "",
  "<a href=\"https://example.com\" data-linkpreview></a>",
  "",
  "\\",
  "*Ждём ответ от **Анны**.*",
  "",
  "---",
  "",
  "## \\",
  "Запись на подачу документов\\",
  "В ближайшие недели по адресу:\\",
  "Центр приёма документов\\",
  "\\",
  "Номер талона - 123456\\",
  "Код брони - A123B456\\",
  "\\",
  "Ссылка на запись:\\",
  "<https://example.com/visit?id=123456>\\\\",
  "",
  "\\",
  "-----",
  "",
  "**Подтверждение записи**",
  "",
  "на 05.11.2026 в 10:30\\",
  "окно 3\\",
  "Номер талона - 123456\\",
  "Код брони - A123B456",
  "",
  "\\",
  "---",
].join("\n");

async function openNote(page: Page, content = CONTENT) {
  const spaces = await (await page.request.get("/api/spaces")).json();
  const resp = await page.request.post("/api/items", {
    data: { space_id: spaces[0].id, title: "Паспорт Яна", content },
  });
  const id = (await resp.json()).id;
  await page.goto(`/?item=${id}`);
  await expect(page.locator(".ProseMirror")).toContainText("Код брони - A123B456");
  // Дать коллаборации подключиться — как у человека, который читает
  // заметку секунду-другую перед правкой.
  await page.waitForTimeout(1500);
}

// Координата правого края последнего символа строки с этим текстом —
// ровно туда, куда человек целится мышкой, «ставя курсор в конец строки».
async function lineEnd(page: Page, text: string, which: "first" | "last") {
  const pt = await page.evaluate(
    ({ text, which }) => {
      const root = document.querySelector(".ProseMirror")!;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const nodes: Text[] = [];
      let n: Node | null;
      while ((n = walker.nextNode())) if ((n as Text).data.includes(text)) nodes.push(n as Text);
      const node = which === "first" ? nodes[0] : nodes[nodes.length - 1];
      if (!node) return null;
      node.parentElement?.scrollIntoView({ block: "center" });
      const end = node.data.indexOf(text) + text.length;
      const r = document.createRange();
      r.setStart(node, end - 1);
      r.setEnd(node, end);
      const rect = r.getBoundingClientRect();
      return { x: rect.right, y: rect.top + rect.height / 2 };
    },
    { text, which },
  );
  if (!pt) throw new Error(`нет строки «${text}»`);
  return pt;
}

async function editorText(page: Page) {
  return page.evaluate(() => (document.querySelector(".ProseMirror") as HTMLElement).innerText);
}

async function clickAndType(page: Page, pt: { x: number; y: number }, typed: string) {
  await page.mouse.click(pt.x, pt.y);
  await page.waitForTimeout(150);
  await page.keyboard.type(typed);
  await page.waitForTimeout(300);
  return editorText(page);
}

test("конец строки с жёстким переносом в середине абзаца", async ({ page }) => {
  await openNote(page);
  const hrBefore = await page.locator(".ProseMirror hr").count();
  const pt = await lineEnd(page, "Номер талона - 123456", "first");
  const text = await clickAndType(page, { x: pt.x + 1, y: pt.y }, "QQ");
  expect(text).toContain("Номер талона - 123456QQ");
  // Линия наверху заметки на месте — набранное её не заменило.
  expect(await page.locator(".ProseMirror hr").count()).toBe(hrBefore);
});

test("конец последней строки абзаца перед пустой строкой", async ({ page }) => {
  await openNote(page);
  const pt = await lineEnd(page, "Код брони - A123B456", "last");
  const text = await clickAndType(page, { x: pt.x + 1, y: pt.y }, "ZZ");
  expect(text).toContain("Код брони - A123B456ZZ");
});

test("клик правее текста строки, в пустоту абзаца", async ({ page }) => {
  await openNote(page);
  const pt = await lineEnd(page, "окно 3", "first");
  const text = await clickAndType(page, { x: pt.x + 150, y: pt.y }, "WW");
  expect(text).toContain("окно 3WW");
});

test("Enter в конце строки создаёт новую строку", async ({ page }) => {
  await openNote(page);
  const pt = await lineEnd(page, "Центр приёма документов", "first");
  await page.mouse.click(pt.x + 1, pt.y);
  await page.waitForTimeout(150);
  await page.keyboard.press("Enter");
  await page.keyboard.type("NN");
  await page.waitForTimeout(300);
  expect(await editorText(page)).toContain("NN");
});

test("выделил линию кликом, потом кликнул в конец строки — печатает там, линия цела", async ({ page }) => {
  await openNote(page, `Первая строка\\\nВторая строка\n\n---\n\nКод брони - A123B456`);
  const editor = page.locator(".ProseMirror");
  const hr = (await editor.locator("hr").first().boundingBox())!;
  await page.mouse.click(hr.x + hr.width / 2, hr.y + Math.max(1, hr.height / 2));
  await expect(editor.locator(".ProseMirror-selectednode")).toHaveCount(1);
  const pt = await lineEnd(page, "Первая строка", "first");
  const text = await clickAndType(page, { x: pt.x + 1, y: pt.y }, "YY");
  expect(text).toContain("Первая строкаYY");
  await expect(editor.locator("hr")).toHaveCount(1);
});

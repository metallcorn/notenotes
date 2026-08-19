import { test, expect } from "@playwright/test";

// Против настоящего живого редактора (TipTap/ProseMirror) — то, что RTL/jsdom
// не может надёжно проверить (см. src/components/*.test.tsx и комментарий в
// последнем коммите про границы покрытия). Единый сквозной пользовательский
// сценарий на файл — не микро-юниты — так E2E оправдывает свою цену
// (медленный, настоящий браузер) вместо дублирования того, что уже
// покрыто быстрыми тестами.

test("создаёт заметку, вставляет заголовок через /, содержимое переживает reload", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("button", { name: "+ Заметка" }).click();

  const editor = page.locator(".ProseMirror");
  await expect(editor).toBeVisible();
  await editor.click();

  await page.keyboard.type("/");
  await page.getByTestId("slash-command-menu").getByRole("button", { name: "Заголовок 1", exact: true }).click();
  await page.keyboard.type("Список покупок");

  await page.keyboard.press("Enter");
  await page.keyboard.type("Обычный текст под заголовком");

  // Дожидаемся реального автосейва (дебаунс 1.2с в NoteEditor.tsx) по
  // самому факту PATCH-запроса — не по статусу в шапке: для новой заметки
  // живая коллаборация включена по умолчанию, и тогда шапка показывает не
  // текст "Сохранено", а просто иконку (см. NoteEditor.tsx, collabStatus
  // === "connected"). Слушатель регистрируем ДО ассертов ниже, чтобы не
  // упустить ответ, если он придёт быстрее, чем мы успеем дойти до await.
  const savePatch = page.waitForResponse(
    (resp) => resp.request().method() === "PATCH" && /\/api\/items\/[0-9a-f-]+$/.test(new URL(resp.url()).pathname),
    { timeout: 5000 },
  );

  await expect(editor.locator("h1")).toHaveText("Список покупок");
  await expect(editor.locator("p", { hasText: "Обычный текст под заголовком" })).toBeVisible();

  await savePatch;
  await page.reload();

  const reloadedEditor = page.locator(".ProseMirror");
  await expect(reloadedEditor.locator("h1")).toHaveText("Список покупок");
  await expect(reloadedEditor.locator("p", { hasText: "Обычный текст под заголовком" })).toBeVisible();
});

test("заметка из одной картинки без единого слова текста переживает reload", async ({ page }) => {
  // Реальный найденный баг (2026-08-19, дважды за день): заметка, чьё ЕДИНСТВЕННОЕ
  // содержимое — атом-узел без текста (картинка/встроенная таблица/вложение),
  // при пересоздании Yjs-комнаты (что происходит на каждом reload — предыдущее
  // соединение закрывается, следующее открытие снова "сеятель" свежей комнаты)
  // "сеялась" пустой из-за эвристики, угадывавшей пустоту по структуре
  // документа вместо исходной строки (см. lib/collabState.ts). Заводим заметку
  // напрямую через API (без реальной загрузки файла — не важно, что картинка
  // битая, важно, что markdown непустой и это ОДИН атом-узел без текста),
  // открываем её (это и есть свежий "посев" комнаты) и проверяем, что
  // содержимое остаётся на месте после reload.
  const spacesResp = await page.request.get("/api/spaces");
  const spaces = await spacesResp.json();
  const spaceId = spaces[0].id;

  const createResp = await page.request.post("/api/items", {
    data: { space_id: spaceId, title: "", content: "![тест](https://example.com/x.png)" },
  });
  const item = await createResp.json();

  await page.goto(`/?item=${item.id}`);
  const editor = page.locator(".ProseMirror");
  await expect(editor.locator("img")).toBeVisible();

  await page.reload();

  const reloadedEditor = page.locator(".ProseMirror");
  await expect(reloadedEditor.locator("img")).toBeVisible();
});

test("маркированный список через / создаёт настоящий <ul><li>", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "+ Заметка" }).click();

  const editor = page.locator(".ProseMirror");
  await editor.click();
  await page.keyboard.type("/спис");
  await page.getByTestId("slash-command-menu").getByRole("button", { name: "Маркированный список", exact: true }).click();
  await page.keyboard.type("Молоко");
  await page.keyboard.press("Enter");
  await page.keyboard.type("Хлеб");

  const items = editor.locator("ul li");
  await expect(items).toHaveCount(2);
  await expect(items.nth(0)).toHaveText("Молоко");
  await expect(items.nth(1)).toHaveText("Хлеб");
});

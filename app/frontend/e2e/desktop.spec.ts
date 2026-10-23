import { test, expect } from "@playwright/test";

// Десктоп (1440×900, проект chromium): скриншоты трёх колонок после
// редизайна — боковая колонка, список, заметка с панелью форматирования.
// Проверка одна: всё, что должно быть на экране, видно; остальное — глазами
// по test-results/desktop-*.png.

test("десктоп: боковая колонка, список, заметка", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("button", { name: "+ Заметка" })).toBeVisible();
  await page.getByText("Все заметки").first().click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: "test-results/desktop-list.png" });

  await page.getByRole("button", { name: "+ Заметка" }).click();
  const editor = page.locator(".ProseMirror");
  await expect(editor).toBeVisible();
  await editor.click();
  await page.keyboard.type("Проверка десктопной шапки");
  await page.getByPlaceholder("Без названия").fill("Десктопная заметка");
  await expect(page.getByTitle("Заголовок 1")).toBeVisible();
  await expect(page.getByTitle("WYSIWYG")).toBeVisible();
  await page.waitForTimeout(600);
  await page.screenshot({ path: "test-results/desktop-editor.png" });
});

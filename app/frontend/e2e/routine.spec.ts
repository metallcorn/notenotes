import { test, expect, type Page } from "@playwright/test";

// Рутина (26.10): создать через шторку «Создать», увидеть открытый приём в
// карточке «Сегодня», отметить «Дал» через шторку отметки — приём закрыт,
// в карточке появился следующий. Данные вымышленные.

// На десктопе кнопка «Новая рутина» — в шапке списка рядом со списком и
// таблицей; на телефоне — плитка в шторке «Создать» нижней панели.
async function openRoutineForm(page: Page) {
  await expect(async () => {
    const header = page.locator('[title="Новая рутина"]:visible').first();
    if (await header.isVisible()) {
      await header.click({ timeout: 2000 });
      return;
    }
    const sheet = page.getByRole("dialog", { name: "Создать" });
    const inNav = page.getByRole("navigation", { name: "Разделы" }).getByRole("button", { name: "Создать" });
    if (!(await sheet.count()) && (await inNav.isVisible())) await inNav.click();
    if (await sheet.count()) {
      await expect(sheet).toBeVisible({ timeout: 3000 });
      // Шторка выезжает 0.26 с — WebKit не кликает по движущейся кнопке.
      await page.waitForTimeout(400);
      await sheet.locator('[title="Новая рутина"]').click({ timeout: 3000 });
      return;
    }
    await page.locator("button:visible:has(svg.lucide-chevron-left)").first().click({ timeout: 1500 });
    throw new Error("ещё не на списке");
  }).toPass({ timeout: 20_000 });
}

test("рутина: создать, отметить приём, увидеть следующий", async ({ page }) => {
  await page.goto("/");
  await openRoutineForm(page);

  const form = page.getByRole("dialog", { name: "Новая рутина" });
  await expect(form).toBeVisible();
  await page.waitForTimeout(400);
  await form.getByPlaceholder("Название, например «Таблетка коту»").fill("Таблетка Бурку");
  await form.getByPlaceholder("Преднизолон, ½ таблетки, с едой").fill("полтаблетки с едой");
  await form.getByRole("button", { name: "Создать рутину" }).click();

  // Экран рутины: заголовок, карточка «Сегодня» с открытым приёмом и «Дал».
  await expect(page.getByRole("heading", { name: "Таблетка Бурку" })).toBeVisible({ timeout: 15_000 });
  const today = page.getByRole("region", { name: "Сегодня" });
  await expect(today).toBeVisible();
  await expect(today.getByRole("button", { name: "Дал", exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/routine-screen.png" });

  await today.getByRole("button", { name: "Дал", exact: true }).click();
  const done = page.getByRole("dialog", { name: "Дал" });
  await expect(done).toBeVisible();
  await page.waitForTimeout(400);
  await done.getByRole("button", { name: /^Дал в / }).click();

  // Приём закрыт: в карточке — галочка с именем и временем, и новый «Дал»
  // для следующего приёма (расписание по умолчанию — два раза в день).
  await expect(done).toBeHidden();
  await expect(today.getByText(/ в \d{2}:\d{2}$/).first()).toBeVisible({ timeout: 10_000 });
  await expect(today.getByText(/Следующий/)).toBeVisible();
  await expect(page.getByText(/1 приёмов/)).toBeVisible();
});

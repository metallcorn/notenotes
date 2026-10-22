import { test, expect, type Page } from "@playwright/test";

// Тёмная тема на телефоне: та же проверка «все кнопки достижимы», что в
// mobile.spec.ts, плюс скриншоты — после редизайна 21.10 тёмная палитра
// переведена на новые роли, и регресс там виден только глазами.
// prefers-color-scheme: dark при настройке «Системная» (по умолчанию)
// включает .dark на <html> (index.html, lib/theme.ts).
test.use({ colorScheme: "dark", viewport: { width: 390, height: 844 } });

async function unreachableControls(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    const out: string[] = [];
    const scrollsX = (el: Element | null): boolean => {
      for (let p = el?.parentElement; p; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX;
        if ((ox === "auto" || ox === "scroll") && p.scrollWidth > p.clientWidth + 1) return true;
      }
      return false;
    };
    for (const el of document.querySelectorAll<HTMLElement>("button, a[href], input:not([type=hidden]), select")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (r.bottom < 0 || r.top > window.innerHeight * 3) continue;
      if (r.left >= -1 && r.right <= vw + 1) continue;
      if (scrollsX(el)) continue;
      out.push((el.getAttribute("aria-label") || el.getAttribute("title") || el.textContent || el.tagName).trim().slice(0, 40));
    }
    return out;
  });
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `test-results/dark-${name}.png` });
  expect.soft(await unreachableControls(page), `экран «${name}»`).toEqual([]);
}

test("тёмная тема: главная, список, шторка, заметка", async ({ page }) => {
  test.setTimeout(60_000);
  await page.goto("/");
  await expect(page.locator("html")).toHaveClass(/dark/);
  // На Главную — кнопкой нижней панели, она есть на любом экране кроме
  // редактора; из редактора сначала «назад».
  // Кнопки — внутри нижней панели: у кнопки «назад» на списке тот же
  // aria-label «Главная».
  const nav = page.getByRole("navigation", { name: "Разделы" });
  const home = nav.getByRole("button", { name: "Главная" });
  if (!(await home.isVisible())) await page.locator("button:visible:has(svg.lucide-chevron-left)").first().click();
  await home.click();
  await expect(page.getByText("Спейсы")).toBeVisible();
  await shot(page, "home");

  await nav.getByRole("button", { name: "Заметки" }).click();
  await page.waitForTimeout(500);
  await shot(page, "list");

  await nav.getByRole("button", { name: "Создать" }).click();
  const sheet = page.getByRole("dialog", { name: "Создать" });
  await expect(sheet).toBeVisible();
  await page.waitForTimeout(400);
  await shot(page, "create");
  await sheet.locator('[title="Новая заметка"]').click();
  await expect(page.locator(".ProseMirror")).toBeVisible();
  await page.locator(".ProseMirror").click();
  await page.keyboard.type("Тёмная тема");
  await shot(page, "editor");

  await page.getByTitle("Действия с заметкой").click();
  await page.waitForTimeout(400);
  await shot(page, "note-menu");
});

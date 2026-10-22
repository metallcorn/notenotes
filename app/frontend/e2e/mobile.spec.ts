import { test, expect, type Page } from "@playwright/test";

// Телефон: на узком экране кнопки, не влезшие в строку, оказывались за
// правым краем без возможности до них доскроллить (жалоба 21.10: «верхняя
// строка не скроллится влево-вправо, часть кнопок недоступна»). jsdom
// раскладки не считает — ловится только настоящим браузером.
//
// Правило проверки: каждая видимая кнопка либо целиком на экране, либо
// внутри контейнера, который сам прокручивается по горизонтали. Обрезанная
// кнопка в overflow-hidden — недоступна, это и есть баг.

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
    const controls = document.querySelectorAll<HTMLElement>(
      "button, a[href], input:not([type=hidden]), select, [role=button]",
    );
    for (const el of controls) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const st = getComputedStyle(el);
      if (st.visibility === "hidden" || st.display === "none") continue;
      // Скрытые за пределами экрана намеренно (sr-only, выезжающие панели
      // вне вида) — их не видно и по вертикали тоже.
      if (r.bottom < 0 || r.top > window.innerHeight * 3) continue;
      if (r.left >= -1 && r.right <= vw + 1) continue;
      if (scrollsX(el)) continue;
      const name = (el.getAttribute("aria-label") || el.getAttribute("title") || el.textContent || el.tagName)
        .trim()
        .slice(0, 40);
      out.push(`${name} [${Math.round(r.left)}..${Math.round(r.right)} из ${vw}]`);
    }
    if (document.documentElement.scrollWidth > vw + 1) {
      out.push(`вся страница шире экрана: ${document.documentElement.scrollWidth} > ${vw}`);
    }
    return out;
  });
}

async function check(page: Page, screen: string) {
  await page.screenshot({ path: `test-results/mobile-${screen}.png` });
  expect.soft(await unreachableControls(page), `экран «${screen}»`).toEqual([]);
}

// Создание на телефоне — через «+» нижней панели (шторка «Создать»), на
// десктопе — кнопки в шапке списка. Один помощник на оба случая.
async function create(page: Page, title: "Новая заметка" | "Новый список" | "Новая таблица") {
  // После goto приложение может открыться сразу в редакторе последней
  // заметки — там нижней панели нет; возвращаемся к списку и пробуем снова.
  await expect(async () => {
    const sheet = page.getByRole("dialog", { name: "Создать" });
    const plus = page.locator('[title="Создать"]:visible');
    if ((await sheet.count()) || (await plus.count())) {
      if (!(await sheet.count())) await plus.first().click();
      await expect(sheet).toBeVisible();
      // Шторка выезжает снизу 0.26 с — WebKit считает кнопку нестабильной,
      // пока идёт анимация, и клик не проходит.
      await page.waitForTimeout(400);
      // На планшетной ширине за шторкой видны и кнопки шапки списка с теми
      // же title — ищем только внутри шторки.
      await sheet.locator(`[title="${title}"]`).click({ timeout: 5000 });
      return;
    }
    const header =
      title === "Новая заметка"
        ? page.getByRole("button", { name: "+ Заметка" })
        : page.locator(`[title="${title}"]:visible`).first();
    if (await header.isVisible()) {
      await header.click({ timeout: 3000 });
      return;
    }
    await page.locator("button:visible:has(svg.lucide-chevron-left)").first().click({ timeout: 1500 });
    throw new Error("ещё не на списке");
  }).toPass({ timeout: 20_000 });
}

async function openSidebar(page: Page) {
  if (await page.getByText("Все заметки").isVisible()) return;
  await page.locator("button:visible:has(svg.lucide-chevron-left)").first().click();
  await expect(page.getByText("Все заметки")).toBeVisible();
}

for (const vp of [
  { name: "phone", width: 360, height: 780 },
  { name: "phone-wide", width: 430, height: 932 },
  { name: "landscape", width: 844, height: 390 },
  { name: "tablet", width: 820, height: 1180 },
  { name: "small-laptop", width: 1100, height: 800 },
]) {
test.describe(vp.name, () => {
test.use({ viewport: { width: vp.width, height: vp.height } });

test("все кнопки достижимы", async ({ page }) => {
  // Семь экранов подряд; WebKit на планшетной ширине не укладывается в 30 с.
  test.setTimeout(90_000);
  const shot = (screen: string) => check(page, `${vp.name}-${screen}`);
  await page.goto("/");
  const createBtn = page
    .locator('[title="Создать"]:visible, [title="Новая заметка"]:visible, button:visible:has-text("+ Заметка")')
    .first();
  await expect(createBtn).toBeVisible();
  await shot("list");

  await openSidebar(page);
  await shot("sidebar");

  for (const [label, screen] of [
    ["Ассистент", "assistant"],
    ["Активность", "activity"],
    ["Документы", "documents"],
  ] as const) {
    await page.getByRole("button", { name: label, exact: true }).first().click();
    await page.waitForTimeout(600);
    await shot(screen);
    await openSidebar(page);
  }

  await page.getByText("Все заметки").click();
  await expect(createBtn).toBeVisible();
  await create(page, "Новая заметка");
  const editor = page.locator(".ProseMirror");
  await expect(editor).toBeVisible();
  await editor.click();
  await page.keyboard.type("Проверка ширины");
  await shot("editor");

  const more = page.getByTitle("Действия с заметкой");
  if (await more.isVisible()) {
    await more.click();
    await page.waitForTimeout(300);
    await shot("note-actions");
    await page.keyboard.press("Escape");
    await page.mouse.click(5, 400);
  }

  for (const [title, screen] of [
    ["Новый список", "list-item"],
    ["Новая таблица", "table-item"],
  ] as const) {
    await page.goto("/");
    // После goto приложение может открыться на панели спейсов (помнит
    // последний экран), а переход между панелями анимирован.
    await expect(async () => {
      const all = page.getByText("Все заметки");
      if (await all.isVisible()) await all.click();
      await create(page, title);
    }).toPass({ timeout: 15_000 });
    await page.waitForTimeout(1200);
    await shot(screen);
  }
});
});
}

test("панель форматирования прокручивается пальцем", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "касания через CDP есть только в Chromium");
  await page.setViewportSize({ width: 360, height: 780 });
  await page.goto("/");
  await create(page, "Новая заметка");
  await expect(page.locator(".ProseMirror")).toBeVisible();
  const h1 = page.getByTitle("Заголовок 1");
  const y = (await h1.boundingBox())!.y + 10;
  // synthesizeScrollGesture в безголовом Chromium не скроллит ничего —
  // только честные touchStart/Move/End.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: 330, y }] });
  for (let i = 1; i <= 10; i++) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: 330 - i * 25, y }] });
    await page.waitForTimeout(16);
  }
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await page.waitForTimeout(300);
  expect(await h1.evaluate((el) => (el.closest(".overflow-x-auto") as HTMLElement).scrollLeft)).toBeGreaterThan(50);
});

test("у края панели форматирования видно, что дальше есть ещё", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await page.goto("/");
  await create(page, "Новая заметка");
  await expect(page.locator(".ProseMirror")).toBeVisible();
  const right = page.getByTitle("Прокрутить панель вправо");
  await expect(right).toBeVisible();
  await expect(page.getByTitle("Прокрутить панель влево")).toHaveCount(0);

  await page.getByTitle("Заголовок 1").evaluate((el) => {
    (el.closest(".overflow-x-auto") as HTMLElement).scrollLeft = 200;
  });
  await expect(page.getByTitle("Прокрутить панель влево")).toBeVisible();
});

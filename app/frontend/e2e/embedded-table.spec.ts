import { test, expect } from "@playwright/test";

// Фича, которую я построил и задеплоил в этой же сессии без единой живой
// проверки в браузере (rich-таблица, встраиваемая в текст заметки через
// /) — теперь проверяем по-настоящему: слэш-команда → модалка создания →
// живой TableGrid внутри заметки → правки переживают reload → страница
// таблицы отдельно открывается по её собственной ссылке.

test("вставляет новую таблицу через /, добавляет столбец и строку, данные переживают reload", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "+ Заметка" }).click();

  const editor = page.locator(".ProseMirror");
  // Редактор может пересоздаться сразу после открытия (подключение
  // совместной правки) — щелчок по старому узлу фокуса не даёт.
  await expect(async () => {
    await editor.click();
    await expect(editor).toBeFocused({ timeout: 1000 });
  }).toPass({ timeout: 10_000 });
  // Без фильтра слэш-меню показывает только первые 10 пунктов
  // (SlashCommand.tsx: .slice(0, 10)) — "Таблица" 12-я по счёту, нужен
  // фильтр, чтобы она попала в выдачу.
  // Без ожидания фокуса «/» иногда уходил до того, как редактор готов, и
  // меню не открывалось — в заметку печатался просто текст «/табл».
  await page.keyboard.type("/");
  await expect(page.getByTestId("slash-command-menu")).toBeVisible();
  await page.keyboard.type("табл");
  await page.getByTestId("slash-command-menu").getByRole("button", { name: "Таблица", exact: true }).click();

  // Вставка узла tableEmbed меняет content самой ЗАМЕТКИ — это отдельный
  // дебаунс-автосейв (1.2с, NoteEditor.tsx), не то же самое, что данные
  // таблицы ниже. Ловим его PATCH явно, до reload — иначе page.reload()
  // рискует оборвать ещё не улетевший запрос браузером (реально пойманная
  // гонка при первом прогоне этого теста: заметка сохранялась пустой).
  const noteSavePatch = page.waitForResponse(
    (resp) => resp.request().method() === "PATCH" && /\/api\/items\/[0-9a-f-]+$/.test(new URL(resp.url()).pathname),
    { timeout: 5000 },
  );

  // Модалка InsertTableModal — режим "Новая" открыт по умолчанию.
  await page.getByPlaceholder("Название таблицы").fill("Расходы на поездку");
  await page.getByRole("button", { name: "Создать" }).click();

  const card = page.getByTestId("table-embed-card");
  await expect(card.getByText("Пока нет ни одного столбца — добавьте первый ниже")).toBeVisible();

  await card.getByRole("button", { name: "Столбец" }).click();
  await card.getByPlaceholder("Название столбца").fill("Категория");
  await card.getByRole("button", { name: "OK" }).click();

  await expect(card.locator("th", { hasText: "Категория" })).toBeVisible();

  // Enter в поле строки — надёжнее, чем искать безымянную (иконка без
  // aria-label) кнопку сабмита среди нескольких форм в карточке; обычная
  // форма, Enter в текстовом поле сабмитит её нативно.
  await card.getByPlaceholder("Категория").fill("Билеты");
  await card.getByPlaceholder("Категория").press("Enter");

  // Строка сохраняется отдельным немедленным POST (useAddTableRow), не
  // дебаунс-автосейвом заметки — к этому моменту он уже гарантированно
  // прошёл (значение в DOM пришло из ответа сервера через кеш react-query,
  // не оптимистично), лишний wait не нужен.
  await expect(card.locator("td input[value='Билеты']")).toBeVisible();

  await noteSavePatch;
  await page.reload();

  const reloadedCard = page.getByTestId("table-embed-card");
  await expect(reloadedCard.locator("th", { hasText: "Категория" })).toBeVisible();
  await expect(reloadedCard.locator("td input[value='Билеты']")).toBeVisible();

  // "Открыть как отдельную страницу" — тот же ?item= deep-link, что
  // используют кнопки в Telegram-боте (см. notification_dispatch.py).
  await reloadedCard.getByTitle("Открыть как отдельную страницу").click();
  await expect(page).toHaveURL(/[?&]item=/);
  await expect(page.getByPlaceholder("Название таблицы")).toHaveValue("Расходы на поездку");
});

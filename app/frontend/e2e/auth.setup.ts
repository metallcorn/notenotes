import { test as setup, expect } from "@playwright/test";

// Логин/пароль должны совпадать с тем, что сеет scripts/e2e-test.sh
// (docker exec ... python3 -, USERNAME/PASSWORD) — это один и тот же
// фиксированный тестовый пользователь в notenotes_test.
const USERNAME = "e2e_test";
const PASSWORD = "e2e_test_password_123";

setup("authenticate", async ({ page }) => {
  await page.goto("/login");
  await page.locator('input[name="username"]').fill(USERNAME);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  // Не проверяем точный URL — AppShell после логина сам уходит на
  // "/?list=1" (bootstrap-эффект в AppShell.tsx), это внутренняя механика,
  // не то, что важно тут проверить. Экран со списком заметок — надёжный
  // сигнал, что сессия реально принята сервером и приложение её видит.
  await expect(page.getByRole("button", { name: "+ Заметка" })).toBeVisible();
  await page.context().storageState({ path: "e2e/.auth/user.json" });
});

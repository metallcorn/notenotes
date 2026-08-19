import { defineConfig, devices } from "@playwright/test";

// Гоняется ТОЛЬКО против одноразового изолированного бэкенда
// (scripts/e2e-test.sh — notenotes_test БД, все внешние ключи обнулены,
// не прод). BASE_URL приходит от него же; localhost:8811 — тот же порт,
// на котором скрипт публикует контейнер, для ручного запуска без скрипта
// (бэкенд уже поднят локально самим разработчиком).
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // Тесты делят одного и того же сидированного пользователя/спейс в БД —
  // параллельные воркеры гонялись бы друг с другом за одни и те же данные.
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.BASE_URL ?? "http://127.0.0.1:8811",
    // Явно выше lg: (1024px) — AppShell показывает три панели рядом только
    // от этой ширины, ниже переключается на мобильную одну-панель-за-раз
    // навигацию, что для этих тестов не нужно.
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: "e2e/.auth/user.json" },
      dependencies: ["setup"],
    },
  ],
});

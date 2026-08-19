import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Отдельный конфиг, не секция test{} внутри vite.config.ts — тот уже несёт
// прод-специфичный proxy (используется только npm run dev), незачем его
// тянуть в тестовый ран. Vitest сам подхватывает vitest.config.ts вместо
// vite.config.ts, если он есть.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    css: false,
  },
});

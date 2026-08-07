import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Дев-сервер (npm run dev) проксирует /api на backend — используется только
// если когда-нибудь появится локальное окружение. Продакшен-сборка отдаётся
// самим FastAPI (app/backend/app/main.py), прокси здесь не участвует.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});

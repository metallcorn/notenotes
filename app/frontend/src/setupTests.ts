import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// RTL обычно регистрирует cleanup сама, но только если детектит глобальный
// afterEach (то есть test.globals: true в конфиге) — здесь его нет
// намеренно (globals засоряли бы tsc, который проверяет всё под src/, тем
// же тайпчеком, что и прод-сборку), поэтому чистим DOM между тестами явно.
afterEach(() => {
  cleanup();
});

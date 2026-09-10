import { describe, expect, it } from "vitest";
import { safeNextPath } from "./safeNext";

/**
 * Открытый редиректор через ?next= — классическая дыра, и особенно
 * противная на странице ВХОДА: человек видит настоящий домен Notenotes,
 * честно вводит пароль, и его уносит на чужой сайт уже авторизованным.
 * Страница выглядит подлинной, потому что она подлинная.
 *
 * Параметр появился ради OAuth (подключение по MCP): не вошедшего
 * отправляют на /login?next=/api/oauth/authorize?..., и без возврата поток
 * обрывался бы на пустом месте.
 */
describe("чужой адрес не принимается", () => {
  it.each([
    ["https://фишинг.example", "полный чужой URL"],
    ["http://evil.example/steal", "он же по http"],
    ["//evil.example", "протокол-относительный — браузер читает как другой сайт"],
    ["/\\evil.example", "обратный слэш, некоторые браузеры трактуют как //"],
    ["javascript:alert(1)", "схема javascript"],
    ["evil.example", "без ведущего слэша"],
  ])("%s отбрасывается (%s)", (raw) => {
    expect(safeNextPath(raw)).toBe("/");
  });

  it("закодированный чужой адрес тоже отбрасывается", () => {
    // Проверять надо то, куда пойдём, а не безопасно выглядящую запись:
    // %2F%2Fevil.example после декодирования — это //evil.example.
    expect(safeNextPath("%2F%2Fevil.example")).toBe("/");
    expect(safeNextPath(encodeURIComponent("https://evil.example"))).toBe("/");
  });

  it("битая кодировка не роняет, а отбрасывает", () => {
    expect(safeNextPath("%E0%A4%A")).toBe("/");
  });
});

describe("свой путь проходит", () => {
  it("возвращает путь внутри приложения", () => {
    expect(safeNextPath("/spaces/123")).toBe("/spaces/123");
  });

  it("сохраняет параметры OAuth целиком", () => {
    // Ради этого всё и заведено: потерять хоть один параметр значит
    // оборвать подключение.
    const target = "/api/oauth/authorize?client_id=abc&redirect_uri=https%3A%2F%2Fclaude.ai%2Fcb&state=xyz";
    expect(safeNextPath(encodeURIComponent(target))).toBe(target);
  });

  it("пустое значение ведёт на главную", () => {
    expect(safeNextPath(null)).toBe("/");
    expect(safeNextPath("")).toBe("/");
  });
});

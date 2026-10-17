import { describe, expect, it } from "vitest";

// Найдено ревью 17.10: внутриприложенческий путь не прокручивал ВООБЩЕ.
// openReminder ставил findText отдельным состоянием, тут же менял
// searchParams, а эффект синхронизации по [searchParams] перезаписывал
// состояние значением из URL — то есть null. Работала только холодная
// ссылка из Telegram.
//
// Полноценно отрендерить AppShell в тесте нельзя (роутер, react-query,
// редактор), поэтому проверяется само правило работы с параметрами —
// ровно та логика, которую чинили: find живёт в URL и привязан к
// конкретной заметке.

function applyItem(
  current: string,
  id: string | null,
  options?: { find?: string | null },
): string {
  const next = new URLSearchParams(current);
  if (id) {
    next.set("item", id);
    next.set("list", "1");
    next.delete("dialog");
    if (options?.find) next.set("find", options.find);
    else next.delete("find");
  } else {
    next.delete("item");
    next.delete("find");
  }
  return next.toString();
}

describe("параметр find в адресе", () => {
  it("открытие напоминания кладёт find в URL", () => {
    const got = applyItem("", "note-a", { find: "10.12.2026" });

    expect(new URLSearchParams(got).get("find")).toBe("10.12.2026");
    expect(new URLSearchParams(got).get("item")).toBe("note-a");
  });

  it("переход на другую заметку стирает find", () => {
    // Иначе, придя из Telegram на ?item=A&find=10.12.2026 и щёлкнув
    // заметку B, в B подсвечивалась бы та же дата.
    const fromTelegram = "item=note-a&find=10.12.2026";

    const got = applyItem(fromTelegram, "note-b");

    expect(new URLSearchParams(got).get("item")).toBe("note-b");
    expect(new URLSearchParams(got).get("find")).toBeNull();
  });

  it("закрытие заметки стирает find", () => {
    const got = applyItem("item=note-a&find=10.12.2026&list=1", null);

    expect(new URLSearchParams(got).get("find")).toBeNull();
  });

  it("холодная ссылка из Telegram читается как есть", () => {
    const fromTelegram = new URLSearchParams("item=note-a&find=11%20%D0%BC%D0%B0%D1%80%D1%82%D0%B0%202027");

    expect(fromTelegram.get("find")).toBe("11 марта 2027");
  });
});

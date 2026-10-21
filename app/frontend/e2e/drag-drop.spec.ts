import { test, expect } from "@playwright/test";

// Перетаскивание мышкой (lib/dragItem.ts): HTML5 drag-and-drop jsdom не
// умеет вовсе — только настоящий браузер.

test("заметку и папку можно перетащить мышкой на папку", async ({ page }) => {
  const spaces = await (await page.request.get("/api/spaces")).json();
  const spaceId = spaces.find((s: { is_vault: boolean }) => !s.is_vault).id;
  const mk = async (name: string, parent_id: string | null = null) =>
    (await (await page.request.post("/api/folders", { data: { space_id: spaceId, name, parent_id } })).json()).id;
  const target = await mk("Куда класть");
  const loose = await mk("Бродячая папка");
  const note = await (
    await page.request.post("/api/items", {
      data: { space_id: spaceId, material_type: "note", title: "Перетаскиваемая", content: "x" },
    })
  ).json();

  await page.goto("/");
  const row = page.getByRole("button", { name: /Перетаскиваемая/ });
  const targetRow = page.getByRole("button", { name: "Куда класть", exact: true });
  await expect(row).toBeVisible();
  await row.dragTo(targetRow);

  await expect
    .poll(async () => (await (await page.request.get(`/api/items/${note.id}`)).json()).folder_id)
    .toBe(target);

  // Папка в папку — и обратно в корень через «Без папки».
  await page.getByRole("button", { name: "Бродячая папка", exact: true }).dragTo(targetRow);
  const parentOf = async () =>
    ((await (await page.request.get(`/api/folders?space_id=${spaceId}`)).json()) as { id: string; parent_id: string | null }[])
      .find((f) => f.id === loose)?.parent_id;
  await expect.poll(parentOf).toBe(target);

  // Обратный бросок: родительскую папку — в её же подпапку. Должно
  // молча ничего не произойти, а не устроить цикл.
  await targetRow.dragTo(page.getByRole("button", { name: "Бродячая папка", exact: true }));
  await page.waitForTimeout(500);
  await expect.poll(parentOf).toBe(target);
});

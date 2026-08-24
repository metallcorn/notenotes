import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import FolderTree from "./FolderTree";
import type { Folder } from "../api/types";

const hooks = vi.hoisted(() => ({
  useFolders: vi.fn(),
  useCreateFolder: vi.fn(),
  useUpdateFolder: vi.fn(),
  useDeleteFolder: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);
vi.mock("./FolderMoveModal", () => ({ default: () => null }));

function mockMutation() {
  return { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };
}

function folder(overrides: Partial<Folder> = {}): Folder {
  return { id: "f1", space_id: "s1", parent_id: null, name: "Авто", created_at: "2026-08-01T00:00:00Z", ...overrides };
}

describe("FolderTree — меню папки не обрезается скролл-контейнером", () => {
  it(
    "меню папки рендерится порталом в document.body (вне overflow-hidden предка) и показывает все четыре пункта",
    async () => {
      hooks.useFolders.mockReturnValue({ data: [folder()] });
      hooks.useCreateFolder.mockReturnValue(mockMutation());
      hooks.useUpdateFolder.mockReturnValue(mockMutation());
      hooks.useDeleteFolder.mockReturnValue(mockMutation());

      // Тот же сценарий, что реальная жалоба: сайдбар — единственный
      // overflow-y-auto скролл-контейнер (AppShell.tsx), в котором рядом со
      // спейсом лежит ещё один спейс ниже — воспроизводим клипающего предка
      // напрямую, а не полагаемся на визуальную геометрию (jsdom её не
      // считает), и проверяем, что меню оказалось СНАРУЖИ него.
      const { container } = render(
        <div style={{ overflow: "hidden", height: 50 }} data-testid="clipping-ancestor">
          <FolderTree spaceId="s1" selectedFolderId={null} onSelect={() => {}} />
        </div>,
      );

      const user = userEvent.setup();
      await user.click(screen.getByTitle("Действия с папкой"));

      const clippingAncestor = container.querySelector('[data-testid="clipping-ancestor"]');
      const menuMoveButton = screen.getByText("Перенести в другой спейс");
      expect(clippingAncestor?.contains(menuMoveButton)).toBe(false);
      expect(document.body.contains(menuMoveButton)).toBe(true);

      expect(screen.getByText("Подпапка")).toBeInTheDocument();
      expect(screen.getByText("Переименовать")).toBeInTheDocument();
      expect(screen.getByText("Удалить")).toBeInTheDocument();
    },
  );
});

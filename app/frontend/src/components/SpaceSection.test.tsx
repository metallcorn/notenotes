import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SpaceSection from "./SpaceSection";
import type { Space } from "../api/types";

const hooks = vi.hoisted(() => ({
  useDeleteSpace: vi.fn(),
  useUpdateSpace: vi.fn(),
  useSpaceMembers: vi.fn(),
}));
vi.mock("../api/hooks", () => hooks);

const vaultSession = vi.hoisted(() => ({ useVaultUnlocked: vi.fn(), lockVault: vi.fn() }));
vi.mock("../lib/vaultSession", () => vaultSession);

vi.mock("./FolderTree", () => ({ default: () => null }));
vi.mock("./PromptDialog", () => ({ default: () => null }));
vi.mock("./SpaceMembersModal", () => ({ default: () => null }));
vi.mock("./VaultChangePasswordModal", () => ({ default: () => null }));
vi.mock("./VaultUnlockOverlay", () => ({ default: () => null }));

function mockMutation() {
  return { mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false };
}

function baseSpace(overrides: Partial<Space> = {}): Space {
  return {
    id: "space-1",
    name: "Дом",
    owner_id: "u1",
    created_at: "2026-08-01T00:00:00Z",
    is_vault: false,
    is_public_pages: false,
    ...overrides,
  };
}

function renderSection(space: Space, memberCount: number) {
  hooks.useDeleteSpace.mockReturnValue(mockMutation());
  hooks.useUpdateSpace.mockReturnValue(mockMutation());
  hooks.useSpaceMembers.mockReturnValue({ data: Array.from({ length: memberCount }, (_, i) => ({ user_id: String(i) })) });
  vaultSession.useVaultUnlocked.mockReturnValue(false);

  return render(
    <SpaceSection
      space={space}
      isActive={false}
      activeFolderId={null}
      collapsed={false}
      onToggleCollapse={() => {}}
      onSelectFolder={() => {}}
    />,
  );
}

describe("SpaceSection — иконка «общий спейс»", () => {
  it("один участник — иконки нет", () => {
    renderSection(baseSpace(), 1);
    expect(screen.queryByTitle("Общий спейс — несколько участников")).not.toBeInTheDocument();
  });

  it("несколько участников — иконка показана", () => {
    renderSection(baseSpace(), 3);
    expect(screen.getByTitle("Общий спейс — несколько участников")).toBeInTheDocument();
  });

  it("список участников ещё не загружен — иконки пока нет (не мигает по 0 в true)", () => {
    hooks.useDeleteSpace.mockReturnValue(mockMutation());
    hooks.useUpdateSpace.mockReturnValue(mockMutation());
    hooks.useSpaceMembers.mockReturnValue({ data: undefined });
    vaultSession.useVaultUnlocked.mockReturnValue(false);

    render(
      <SpaceSection
        space={baseSpace()}
        isActive={false}
        activeFolderId={null}
        collapsed={false}
        onToggleCollapse={() => {}}
        onSelectFolder={() => {}}
      />,
    );
    expect(screen.queryByTitle("Общий спейс — несколько участников")).not.toBeInTheDocument();
  });
});

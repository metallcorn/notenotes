import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ConfirmDialog from "./ConfirmDialog";
import ReminderModal from "./ReminderModal";
import ImageLightbox from "./ImageLightbox";

// Жалоба владельца 12.10: «всё без анимаций» — модалки возникали
// мгновенно, что на тёмной подложке читается как вспышка.
//
// Проверяем не саму анимацию (её рисует CSS), а что класс реально стоит на
// ПОДЛОЖКЕ: панель ловится дочерним селектором .modal-in > *, поэтому
// забытый класс на подложке означает отсутствие анимации и у панели.

describe("появление модалок", () => {
  it("ConfirmDialog", () => {
    const { container } = render(
      <ConfirmDialog title="Удалить?" onConfirm={() => {}} onCancel={() => {}} />,
    );

    expect(container.querySelector(".modal-in")).not.toBeNull();
  });

  it("ReminderModal", () => {
    const { container } = render(
      <ReminderModal defaultTitle="x" onCreate={() => {}} onCancel={() => {}} />,
    );

    expect(container.querySelector(".modal-in")).not.toBeNull();
  });

  it("полноэкранный просмотр картинки", () => {
    const { container } = render(
      <ImageLightbox images={[{ src: "/api/uploads/1", alt: "" }]} onClose={() => {}} />,
    );

    expect(container.querySelector(".modal-in")).not.toBeNull();
  });

  it("класс стоит именно на подложке, а не на панели", () => {
    // Иначе дочерний селектор .modal-in > * поймает не то.
    const { container } = render(
      <ConfirmDialog title="Удалить?" onConfirm={() => {}} onCancel={() => {}} />,
    );
    const animated = container.querySelector(".modal-in")!;

    expect(animated.className).toContain("fixed");
    expect(animated.className).toContain("inset-0");
    expect(animated.children.length).toBeGreaterThan(0);
  });
});

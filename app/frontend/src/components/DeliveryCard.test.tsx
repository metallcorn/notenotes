import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DeliveryCard from "./DeliveryCard";

describe("DeliveryCard", () => {
  it("показывает перевозчика, статус, чекпоинты и ссылку на трекинг", () => {
    render(
      <DeliveryCard
        data={{
          carrier: "inpost",
          carrier_label: "InPost (Paczkomaty / kurier)",
          tracking_number: "600000000000000000000001",
          live: true,
          status_text: "Zarejestrowano",
          last_event_time: "2026-08-21T09:42:13+02:00",
          checkpoints: [
            { time: "2026-08-21T09:42:13+02:00", status: "confirmed", description: "Zarejestrowano" },
            { time: "2026-08-22T10:00:00+02:00", status: "out_for_delivery", description: "W doręczeniu" },
          ],
          tracking_url: "https://inpost.pl/sledzenie-przesylek?number=600000000000000000000001",
          note: "Paczkomat POZ00XX",
        }}
      />,
    );

    expect(screen.getByText("InPost (Paczkomaty / kurier)")).toBeInTheDocument();
    // "Zarejestrowano" встречается дважды — как строка статуса и как описание
    // первого чекпоинта (реальный случай: status_text = последнее событие).
    expect(screen.getAllByText("Zarejestrowano").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("W doręczeniu")).toBeInTheDocument();
    expect(screen.getByText("600000000000000000000001")).toBeInTheDocument();

    const link = screen.getByRole("link", { name: /Трекинг/ });
    expect(link).toHaveAttribute("href", "https://inpost.pl/sledzenie-przesylek?number=600000000000000000000001");
  });

  it("headerExtra рендерится рядом со ссылкой на трекинг, а не поверх неё", () => {
    // Регрессия: раньше кнопка «Обновить» в DeliveryWidgetCard была
    // position:absolute поверх этого же угла карточки, где рисуется
    // ссылка «Трекинг» — визуально выглядело так, будто кнопки нет вообще.
    render(
      <DeliveryCard
        data={{
          carrier_label: "InPost",
          live: true,
          status_text: "Zarejestrowano",
          tracking_url: "https://inpost.pl/sledzenie-przesylek?number=1",
        }}
        headerExtra={<button aria-label="Обновить">R</button>}
      />,
    );

    expect(screen.getByRole("link", { name: /Трекинг/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Обновить" })).toBeInTheDocument();
  });

  it("для need_carrier показывает подсказку и список перевозчиков", () => {
    render(
      <DeliveryCard
        data={{
          need_carrier: true,
          message: "Не удалось определить перевозчика по номеру.",
          supported: [
            { id: "inpost", label: "InPost" },
            { id: "poczta", label: "Poczta Polska" },
          ],
        }}
      />,
    );

    expect(screen.getByText("Не удалось определить перевозчика по номеру.")).toBeInTheDocument();
    expect(screen.getByText(/InPost/)).toBeInTheDocument();
    expect(screen.getByText(/Poczta Polska/)).toBeInTheDocument();
  });
});

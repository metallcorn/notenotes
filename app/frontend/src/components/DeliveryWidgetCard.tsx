import { NodeViewWrapper } from "@tiptap/react";
import type { NodeViewProps } from "@tiptap/react";
import { RotateCw } from "lucide-react";
import { useDeliveryWidget, useRefreshDeliveryWidget } from "../api/hooks";
import DeliveryCard, { type DeliveryData } from "./DeliveryCard";
import Spinner from "./Spinner";

// Постоянный виджет доставки в заметке. В content — только id узла;
// состояние (перевозчик/номер/результат) живёт в delivery_widgets на
// бэкенде и подтягивается сюда при монтировании (useDeliveryWidget), а
// «Обновить» (useRefreshDeliveryWidget) опрашивает перевозчика заново и
// пишет только эту запись — content/Yjs/история версий не задеты.
// Презентация переиспользует DeliveryCard, ту же, что в чате, — виджет и
// чат показывают посылку одинаково.
export default function DeliveryWidgetCard({ node }: NodeViewProps) {
  const { id } = node.attrs as { id: string | null };
  const { data: widget, isLoading } = useDeliveryWidget(id ?? undefined);
  const refresh = useRefreshDeliveryWidget(id ?? undefined);

  if (!id) return null;

  if (isLoading || !widget) {
    return (
      <NodeViewWrapper as="div" className="my-1">
        <div className="max-w-md rounded-lg border bg-muted px-3 py-2 text-xs text-subtle">
          <Spinner size={12} className="mr-1 inline" /> Загрузка…
        </div>
      </NodeViewWrapper>
    );
  }

  // widget.result — уже нормализованный dict (форма DeliveryData). Если
  // последний опрос не удался, показываем минимум из сохранённого.
  const data: DeliveryData =
    (widget.result as DeliveryData | null) ?? {
      carrier: widget.carrier,
      tracking_number: widget.tracking_number,
      live: false,
      status_text: "Статус ещё не получен",
    };

  const refreshButton = (
    <button
      onClick={() => refresh.mutate()}
      disabled={refresh.isPending}
      title="Обновить"
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-subtle hover:bg-muted-hover hover:text-secondary disabled:opacity-50"
    >
      {refresh.isPending ? <Spinner size={13} /> : <RotateCw size={13} />}
    </button>
  );

  return (
    // Реальный найденный баг (тот же класс, что уже чинили в карточках
    // документа/картинки/билета — draggable=true браузер распознаёт по
    // БЛИЖАЙШЕМУ ПРЕДКУ независимо от data-drag-handle, это отдельная,
    // чисто внутренняя проверка TipTap): draggable на обёртке, содержащей
    // ссылку "Трекинг" (обычный <a target=_blank>), заставлял клик по
    // ссылке иногда открывать сразу две вкладки — конфликт между нативным
    // "перетащить ссылку" браузера и обычной навигацией по клику. В
    // отличие от тех карточек, здесь узкий drag-handle без ссылок внутри
    // сделать некуда без переделки самой DeliveryCard (общая с чатом) —
    // проще и безопаснее просто не делать виджет доставки перетаскиваемым
    // как блок целиком: cut/paste всё ещё работает для перестановки.
    <NodeViewWrapper as="div" className="my-1">
      <div className="max-w-md">
        <DeliveryCard data={data} headerExtra={refreshButton} />
        {refresh.isError && <div className="mt-1 text-xs text-danger">Не удалось обновить</div>}
      </div>
    </NodeViewWrapper>
  );
}

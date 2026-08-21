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
        <div className="max-w-md rounded-lg border bg-slate-50 px-3 py-2 text-xs text-slate-400">
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
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-50"
    >
      {refresh.isPending ? <Spinner size={13} /> : <RotateCw size={13} />}
    </button>
  );

  return (
    <NodeViewWrapper as="div" className="my-1">
      <div className="max-w-md" data-drag-handle draggable>
        <DeliveryCard data={data} headerExtra={refreshButton} />
        {refresh.isError && <div className="mt-1 text-xs text-red-600">Не удалось обновить</div>}
      </div>
    </NodeViewWrapper>
  );
}

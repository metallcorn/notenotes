import { useEffect, useState } from "react";
import { useIsRestoring } from "@tanstack/react-query";

const RESTORE_TIMEOUT_MS = 3000;

// useIsRestoring() держит экран в состоянии загрузки, пока
// PersistQueryClientProvider гидрирует кэш из IndexedDB (см. комментарий в
// App.tsx). На части реальных устройств (жалоба — Android Firefox, PWA,
// после жеста «назад») это открытие IndexedDB иногда не завершается вовсе —
// известная особенность браузеров: открытие блокируется, если где-то
// осталось не закрытое соединение к той же базе. Без верхней границы
// экран замирал бы на "Загрузка…" насовсем — тот самый "белый экран и
// ничего" из отзыва. Таймаут не чинит зависшее IndexedDB-соединение, а
// просто перестаёт его ждать: восстановленный кэш просто не подключится в
// этом заходе, данные подтянутся обычным сетевым запросом.
export function useBoundedRestoring(): boolean {
  const isRestoring = useIsRestoring();
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (!isRestoring) {
      setTimedOut(false);
      return;
    }
    const timer = setTimeout(() => setTimedOut(true), RESTORE_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [isRestoring]);

  return isRestoring && !timedOut;
}

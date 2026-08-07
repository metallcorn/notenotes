import { useEffect, useRef, useState } from "react";

const CHECK_INTERVAL_MS = 5 * 60 * 1000;

/**
 * Сверяет текущий раздаваемый бэкендом JS-бандл (имя файла, оно же
 * content-хэш от Vite) с тем, что было при загрузке страницы. Открытая
 * вкладка сама не узнаёт о новом деплое — polling + проверка при возврате
 * фокуса на вкладку закрывают это молча.
 */
export function useVersionCheck(): boolean {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const initialVersion = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        const res = await fetch("/api/version", { credentials: "include" });
        if (!res.ok) return;
        const data = (await res.json()) as { version: string };
        if (cancelled) return;
        if (initialVersion.current === null) {
          initialVersion.current = data.version;
        } else if (data.version !== initialVersion.current) {
          setUpdateAvailable(true);
        }
      } catch {
        // сеть недоступна/офлайн — не считаем это признаком новой версии
      }
    }

    check();
    const interval = setInterval(check, CHECK_INTERVAL_MS);
    function onVisibility() {
      if (document.visibilityState === "visible") check();
    }
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return updateAvailable;
}

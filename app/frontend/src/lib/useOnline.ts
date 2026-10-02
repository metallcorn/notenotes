import { useEffect, useState } from "react";

/**
 * Есть ли сеть. navigator.onLine врёт в одну сторону — говорит «да»,
 * когда wi-fi подключён, но интернета за ним нет. Зато «нет» он говорит
 * честно, а нам нужно именно это: предупредить, что показанное может
 * быть устаревшим.
 */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine);

  useEffect(() => {
    const up = () => setOnline(true);
    const down = () => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  return online;
}

import { useEffect, useState } from "react";
import { api } from "../api/client";

// applicationServerKey ждёт Uint8Array, а публичный VAPID-ключ приходит
// с бэкенда как urlsafe-base64 строка (тот же "raw"-формат, что
// использует pywebpush) — стандартное преобразование, копипаста из
// спеки Push API, другого способа нет.
function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

// iOS 16.4+ поддерживает Web Push, но только для установленного на
// экран PWA-ярлыка — обычная вкладка Safari подписаться не может вообще
// (сам браузер не даёт), это не баг конкретно этого кода.
export function isPushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export function usePushSubscription() {
  const [subscribed, setSubscribed] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!isPushSupported()) {
      setSubscribed(false);
      return;
    }
    navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((sub) => setSubscribed(!!sub))
      .catch(() => setSubscribed(false));
  }, []);

  async function subscribe() {
    setBusy(true);
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") return;
      const { key } = await api.get<{ key: string }>("/push/vapid-public-key");
      if (!key) return;
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        // as BufferSource: TS 5.7's lib.dom typing makes Uint8Array<ArrayBufferLike>
        // (generic default from Uint8Array.from) not directly assignable to
        // BufferSource — a real runtime Uint8Array works fine, this is a
        // type-level mismatch only.
        applicationServerKey: urlBase64ToUint8Array(key) as BufferSource,
      });
      const json = sub.toJSON();
      await api.post("/push/subscribe", { endpoint: json.endpoint, p256dh: json.keys?.p256dh, auth: json.keys?.auth });
      setSubscribed(true);
    } finally {
      setBusy(false);
    }
  }

  async function unsubscribe() {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await api.post("/push/unsubscribe", { endpoint: sub.endpoint });
        await sub.unsubscribe();
      }
      setSubscribed(false);
    } finally {
      setBusy(false);
    }
  }

  return { subscribed, busy, subscribe, unsubscribe };
}

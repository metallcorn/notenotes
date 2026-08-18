import * as Y from "yjs";
import { Awareness, applyAwarenessUpdate, encodeAwarenessUpdate } from "y-protocols/awareness";

// Свой протокол, не y-websocket npm-пакет — свой сервер (app/collab.py) и
// свой seeding-хендшейк, проще написать маленький клиент под свой протокол,
// чем подгонять чужой под другой сервер. Один байт типа в начале каждого
// бинарного WS-сообщения — см. докстринг app/backend/app/collab.py,
// значения должны совпадать буква в букву.
const MSG_UPDATE = 1;
const MSG_AWARENESS = 2;
const MSG_SEED_REQUEST = 3;
const MSG_SEED_COMPLETE = 4;

export type CollabStatus = "connecting" | "connected" | "disconnected";

// Одно на одну заметку, живёт ровно пока эта заметка открыта в редакторе
// (создаётся/уничтожается из NoteEditor.tsx при переключении). doc/awareness
// публичные — их читает collabState.ts, который строит из них плагины
// ProseMirror (ySyncPlugin/yCursorPlugin/yUndoPlugin).
export class CollabProvider {
  readonly doc = new Y.Doc();
  readonly awareness: Awareness;
  private ws: WebSocket | null = null;
  private onStatus: (status: CollabStatus) => void;

  constructor(
    private readonly itemId: string,
    onStatus: (status: CollabStatus) => void,
  ) {
    this.awareness = new Awareness(this.doc);
    this.onStatus = onStatus;
    this.doc.on("update", this.handleDocUpdate);
    this.awareness.on("update", this.handleAwarenessUpdate);
  }

  private handleDocUpdate = (update: Uint8Array, origin: unknown) => {
    // origin === this — апдейт только что пришёл ИЗ сети (applyUpdate ниже
    // передаёт себя origin'ом) — не отправлять его обратно, иначе вечный
    // пинг-понг между клиентом и сервером.
    if (origin === this) return;
    this.send(MSG_UPDATE, update);
  };

  private handleAwarenessUpdate = (
    { added, updated, removed }: { added: number[]; updated: number[]; removed: number[] },
    origin: unknown,
  ) => {
    if (origin === this) return;
    const changed = added.concat(updated, removed);
    if (changed.length === 0) return;
    this.send(MSG_AWARENESS, encodeAwarenessUpdate(this.awareness, changed));
  };

  private send(type: number, payload: Uint8Array) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const msg = new Uint8Array(1 + payload.length);
    msg[0] = type;
    msg.set(payload, 1);
    this.ws.send(msg);
  }

  // Резолвится, когда можно начинать редактировать. onSeedRequested
  // вызывается синхронно, только у самой первой сессии совсем свежей
  // комнаты (см. app/collab.py) — коллбэк должен либо наполнить this.doc
  // текущим содержимым заметки (это само по себе пошлёт апдейт на
  // сервер — см. handleDocUpdate), либо, если наполнять нечем (пустая
  // заметка), явно вызвать markSeedComplete().
  connect(onSeedRequested: () => void): Promise<void> {
    this.onStatus("connecting");
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/api/items/${this.itemId}/collab`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;

    return new Promise((resolve, reject) => {
      let settled = false;

      ws.onmessage = (event) => {
        const data = new Uint8Array(event.data as ArrayBuffer);
        if (data.length === 0) return;
        const type = data[0];
        const payload = data.slice(1);

        if (type === MSG_SEED_REQUEST) {
          try {
            onSeedRequested();
          } catch (err) {
            // Не даём сломанному посеву заморозить соединение навсегда —
            // без этого settled/resolve ниже никогда бы не выполнились, и
            // "Подключение…" висело бы вечно.
            if (!settled) {
              settled = true;
              reject(err instanceof Error ? err : new Error("collab-seed-failed"));
            }
            return;
          }
          if (!settled) {
            settled = true;
            this.onStatus("connected");
            resolve();
          }
        } else if (type === MSG_UPDATE) {
          Y.applyUpdate(this.doc, payload, this);
          if (!settled) {
            settled = true;
            this.onStatus("connected");
            resolve();
          }
        } else if (type === MSG_AWARENESS) {
          applyAwarenessUpdate(this.awareness, payload, this);
        }
      };

      ws.onerror = () => {
        if (!settled) {
          settled = true;
          reject(new Error("collab-ws-error"));
        } else {
          this.onStatus("disconnected");
        }
      };

      ws.onclose = () => {
        if (!settled) {
          settled = true;
          reject(new Error("collab-ws-closed"));
        } else {
          this.onStatus("disconnected");
        }
      };
    });
  }

  markSeedComplete() {
    this.send(MSG_SEED_COMPLETE, new Uint8Array(0));
  }

  disconnect() {
    this.doc.off("update", this.handleDocUpdate);
    this.awareness.off("update", this.handleAwarenessUpdate);
    // setLocalState(null) шлёт остальным финальный awareness-апдейт
    // "меня больше нет" ДО закрытия сокета — иначе курсор этого клиента
    // висел бы у других до истечения таймаута протокола awareness.
    this.awareness.setLocalState(null);
    this.awareness.destroy();
    if (this.ws) {
      this.ws.onmessage = null;
      this.ws.onerror = null;
      this.ws.onclose = null;
      this.ws.close();
      this.ws = null;
    }
    this.doc.destroy();
  }
}

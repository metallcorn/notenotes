import { useEffect, useRef, useState } from "react";
import { Mic, Square, X } from "lucide-react";
import { api } from "../api/client";
import type { UploadResult } from "../api/types";
import { uiStorage } from "../lib/storage";

const MIN_WIDTH = 320;
const MAX_WIDTH = 800;

// Порядок предпочтений — Chrome/Firefox/Safari поддерживают разные наборы,
// opus в webm/ogg лёгкий и достаточно качественный для речи. Реальный
// content_type попадает и в Upload.content_type на бэкенде (там же решает,
// что слать в Deepgram и как отдавать файл обратно <audio src=...>).
function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/ogg"];
  for (const c of candidates) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(c)) return c;
  }
  return "audio/webm";
}

async function postChunk(uploadId: string, body: ArrayBuffer): Promise<void> {
  const res = await fetch(`/api/uploads/recording/${uploadId}/chunk`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/octet-stream" },
    body,
  });
  if (!res.ok) throw new Error(String(res.status));
}

async function postChunkWithRetry(uploadId: string, body: ArrayBuffer, attempt = 0): Promise<void> {
  try {
    await postChunk(uploadId, body);
  } catch (err) {
    // Реальная просьба: обрыв интернета не должен ронять запись целиком —
    // локально MediaRecorder продолжает писать независимо от сети,
    // повторяем отправку куска несколько раз с растущей паузой. Если и
    // это не помогло — теряем именно этот кусок (~10с), не всю запись.
    if (attempt >= 5) throw err;
    await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
    return postChunkWithRetry(uploadId, body, attempt + 1);
  }
}

function formatElapsed(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

type Phase = "idle" | "starting" | "recording" | "finishing" | "done" | "error";

// Реальный запрос: запись встречи/длинной заметки прямо в редакторе, с
// диаризацией (несколько говорящих) — короткая голосовая реплика себе в
// Telegram или диктовка в реальном времени (ассистент, Palabra) уже
// закрыты другими путями, это отдельный случай ("надо во-первых чанково
// писать, чтобы запись не оборвалась... во-вторых это должно с
// диаризацией распознаваться, а это у нас Deepgram").
export default function RecordingPanel({
  spaceId,
  onClose,
  onStarted,
}: {
  spaceId: string;
  onClose: () => void;
  // Вызывается сразу после успешного /recording/start — NoteEditor.tsx
  // вставляет плейсхолдер в позицию, зафиксированную в момент клика
  // "Начать запись" (не в момент открытия панели).
  onStarted: (uploadId: string) => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [elapsedSec, setElapsedSec] = useState(0);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [width, setWidth] = useState(() => uiStorage.getNotePanelWidth());
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia("(min-width: 1024px)").matches);
  const draggingRef = useRef(false);

  const uploadIdRef = useRef<string | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const uploadChainRef = useRef<Promise<void>>(Promise.resolve());
  const timerRef = useRef<number | null>(null);
  const phaseRef = useRef<Phase>("idle");
  const mountedRef = useRef(true);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const rafRef = useRef<number | null>(null);

  phaseRef.current = phase;

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const handler = () => setIsDesktop(mq.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  // Предупреждение браузера при обновлении/закрытии страницы во время
  // записи — реальная просьба защититься от случайной потери. Уже
  // загруженные на сервер чанки при этом не теряются (см. postChunk выше),
  // риск только для ещё не отправленного хвоста.
  useEffect(() => {
    if (phase !== "recording" && phase !== "finishing") return;
    function handler(e: BeforeUnloadEvent) {
      e.preventDefault();
      e.returnValue = "";
    }
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [phase]);

  function stopWaveform() {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    analyserRef.current = null;
    audioContextRef.current?.close();
    audioContextRef.current = null;
  }

  function drawWaveform(data: Uint8Array) {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.beginPath();
    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth = 1.5;
    const step = canvas.width / data.length;
    for (let i = 0; i < data.length; i++) {
      const x = i * step;
      const y = (data[i] / 255) * canvas.height;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  function startWaveform(stream: MediaStream) {
    const audioContext = new AudioContext();
    const source = audioContext.createMediaStreamSource(stream);
    const analyser = audioContext.createAnalyser();
    analyser.fftSize = 2048;
    source.connect(analyser);
    audioContextRef.current = audioContext;
    analyserRef.current = analyser;

    const data = new Uint8Array(analyser.fftSize);
    const tick = () => {
      if (!analyserRef.current) return;
      analyser.getByteTimeDomainData(data);
      drawWaveform(data);
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }

  async function handleStart() {
    setErrorMessage(null);
    setPhase("starting");

    // Реальный найденный баг: раньше сначала звали /recording/start и
    // вставляли плейсхолдер в заметку (onStarted), и только потом
    // запрашивали микрофон — если пользователь запрещал доступ (или его
    // нет физически), плейсхолдер уже был вписан, запись не начиналась,
    // /finish не вызывался никогда, и текст "⏳ Запись..." зависал в
    // заметке навсегда. Микрофон — первым делом, до всего остального.
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setPhase("error");
      setErrorMessage("Нет доступа к микрофону");
      return;
    }

    try {
      const mimeType = pickMimeType();
      const upload = await api.post<UploadResult>("/uploads/recording/start", {
        space_id: spaceId,
        content_type: mimeType,
      });
      uploadIdRef.current = upload.id;
      onStarted(upload.id);

      streamRef.current = stream;
      startWaveform(stream);

      const recorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 32000 });
      recorder.ondataavailable = (e) => {
        if (e.data.size === 0 || !uploadIdRef.current) return;
        const id = uploadIdRef.current;
        uploadChainRef.current = uploadChainRef.current
          .then(() => e.data.arrayBuffer())
          .then((buf) => postChunkWithRetry(id, buf))
          .catch(() => {
            // Кусок потерян после всех попыток — запись продолжается,
            // остальное не рушим.
          });
      };
      recorder.onstop = async () => {
        streamRef.current?.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        stopWaveform();
        try {
          await uploadChainRef.current;
          await api.post(`/uploads/recording/${uploadIdRef.current}/finish`);
          if (mountedRef.current) setPhase("done");
        } catch {
          if (mountedRef.current) {
            setPhase("error");
            setErrorMessage("Не получилось завершить запись");
          }
        }
      };
      mediaRecorderRef.current = recorder;
      recorder.start(10000);
      setPhase("recording");

      setElapsedSec(0);
      timerRef.current = window.setInterval(() => setElapsedSec((s) => s + 1), 1000);
    } catch {
      stream.getTracks().forEach((t) => t.stop());
      setPhase("error");
      setErrorMessage("Не удалось начать запись");
    }
  }

  function handleStop() {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setPhase("finishing");
    mediaRecorderRef.current?.stop();
  }

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (timerRef.current !== null) clearInterval(timerRef.current);
      stopWaveform();
      // Закрыли панель/ушли со страницы заметки во время записи — запись
      // останавливается и уходит на распознавание (решение обсуждено
      // явно), не продолжает молча в фоне.
      if (phaseRef.current === "recording" && mediaRecorderRef.current?.state === "recording") {
        mediaRecorderRef.current.stop();
      } else {
        streamRef.current?.getTracks().forEach((t) => t.stop());
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function onHandlePointerDown(e: React.PointerEvent<HTMLDivElement>) {
    draggingRef.current = true;
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function onHandlePointerMove(e: React.PointerEvent<HTMLDivElement>) {
    if (!draggingRef.current) return;
    const next = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, window.innerWidth - e.clientX));
    setWidth(next);
    uiStorage.setNotePanelWidth(next);
  }
  function onHandlePointerUp(e: React.PointerEvent<HTMLDivElement>) {
    draggingRef.current = false;
    e.currentTarget.releasePointerCapture(e.pointerId);
  }

  function handleClose() {
    // Пишет прямо сейчас — сам handleStop уже запускает finish внутри
    // onstop; закрываем панель сразу, не дожидаясь ответа сервера (то же
    // решение, что и у размонтирования выше — запись не блокирует уход).
    if (phase === "recording") handleStop();
    onClose();
  }

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/40 lg:hidden" onClick={phase === "recording" ? undefined : handleClose} />
      <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center p-4 lg:items-stretch lg:justify-end lg:p-0">
        <div
          style={isDesktop ? { width } : undefined}
          className="panel-slide-in pointer-events-auto relative flex h-auto w-full max-w-xl flex-col overflow-hidden rounded-lg bg-white shadow-xl lg:h-full lg:max-w-none lg:rounded-none lg:border-l lg:shadow-2xl"
        >
          <div
            onPointerDown={onHandlePointerDown}
            onPointerMove={onHandlePointerMove}
            onPointerUp={onHandlePointerUp}
            className="absolute -left-1 top-0 hidden h-full w-2 cursor-col-resize touch-none lg:block"
          />
          <div className="flex items-center justify-between border-b px-3 py-2">
            <span className="text-sm font-medium text-slate-500">Запись</span>
            <button onClick={handleClose} className="flex h-7 w-7 items-center justify-center rounded text-slate-400 hover:bg-slate-100">
              <X size={16} />
            </button>
          </div>

          <div className="flex flex-col items-center gap-4 px-6 py-8">
            {phase === "idle" && (
              <>
                <p className="text-center text-sm text-slate-500">
                  Запись сохраняется по ходу — можно продолжать редактировать заметку, пока идёт запись.
                </p>
                <button
                  onClick={handleStart}
                  className="flex items-center gap-2 rounded-full bg-slate-900 px-5 py-2.5 text-sm text-white hover:bg-slate-800"
                >
                  <Mic size={16} />
                  Начать запись
                </button>
              </>
            )}

            {phase === "starting" && <p className="text-sm text-slate-500">Запрашиваю доступ к микрофону…</p>}

            {phase === "recording" && (
              <>
                <div className="flex items-center gap-2 text-red-600">
                  <span className="h-2 w-2 animate-pulse rounded-full bg-red-600" />
                  <span className="font-mono text-lg">{formatElapsed(elapsedSec)}</span>
                </div>
                <canvas ref={canvasRef} width={280} height={48} className="h-12 w-full max-w-xs" />
                <button
                  onClick={handleStop}
                  className="flex items-center gap-2 rounded-full border border-red-300 bg-red-50 px-5 py-2.5 text-sm text-red-600 hover:bg-red-100"
                >
                  <Square size={14} />
                  Остановить
                </button>
              </>
            )}

            {phase === "finishing" && <p className="text-sm text-slate-500">Заканчиваю запись…</p>}

            {phase === "done" && (
              <>
                <p className="text-center text-sm text-slate-600">
                  Запись отправлена на распознавание — результат появится в заметке через какое-то время.
                </p>
                <button onClick={onClose} className="rounded bg-slate-900 px-4 py-2 text-sm text-white hover:bg-slate-800">
                  Готово
                </button>
              </>
            )}

            {phase === "error" && (
              <>
                <p className="text-center text-sm text-red-600">{errorMessage}</p>
                <button onClick={handleStart} className="rounded border px-4 py-2 text-sm text-slate-600 hover:bg-slate-50">
                  Попробовать снова
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

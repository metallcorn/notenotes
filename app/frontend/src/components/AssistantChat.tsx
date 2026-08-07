import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  AlignCenter,
  CalendarPlus,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Maximize2,
  Mic,
  MapPin,
  Pencil,
  Square,
  StretchHorizontal,
  Trash2,
  Volume2,
  VolumeX,
  Wrench,
} from "lucide-react";
import ReactMarkdown, { type Components } from "react-markdown";
import ReactDOMServer from "react-dom/server";
import remarkGfm from "remark-gfm";
import { useDeleteDialogMessage, useDialog, useSendDialogMessage, useSpeak, useUpdateItem } from "../api/hooks";
import type { DialogMessage } from "../api/types";
import { uiStorage, type ContentWidth } from "../lib/storage";
import { downloadFile, sanitizeFilename, wrapHtmlDocument } from "../lib/export";
import ConfirmDialog from "./ConfirmDialog";
import ExportMenu from "./ExportMenu";
import PromptDialog from "./PromptDialog";
import Spinner from "./Spinner";

// Живой ASR-стрим (Palabra) поверх WebSocket /api/voice/asr-stream: браузер
// шлёт сырые PCM s16le-фреймы, сервер ретранслирует их в Palabra и гоняет
// её транскрипты обратно — так и задумано в ТЗ §10a («разговор с
// ассистентом», не запись одного клипа с батч-загрузкой после).
// Ссылки от ассистента (веб-поиск и т.п.) всегда во внешней вкладке —
// иначе клик уводит из чата совсем, без возврата назад в разумном месте.
const markdownComponents: Components = {
  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
};

const SILENCE_AUTO_SEND_MS = 2000;
const SILENCE_VOLUME_THRESHOLD = 0.02;

function floatTo16BitPCM(input: Float32Array): ArrayBuffer {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return output.buffer;
}

// Тул-вызовы и их результаты хранятся отдельными записями с role="tool" сразу
// после породившей их реплики ассистента (так пишет routers/dialogs.py) —
// группируем их обратно под эту реплику, чтобы показать разворачиваемым
// индикатором, а не отдельным сообщением в ленте.
//
// Один ход агентного цикла может состоять из нескольких итераций (тул →
// результат → снова текст модели) — каждая пишется отдельной assistant-
// записью в транскрипте. Без склейки это разваливается на несколько
// пузырей подряд: один — только кнопка (от тула, content пустой), другой —
// текст ("ссылка появится под этим сообщением"), а сама кнопка на самом
// деле в предыдущем пузыре. Склеиваем подряд идущие assistant-записи (без
// user между ними) в одну — кнопка и текст, который её описывает, тогда
// оказываются в одном пузыре, как и должны.
function groupMessages(messages: DialogMessage[]) {
  const groups: { message: DialogMessage; toolResults: DialogMessage[] }[] = [];
  for (const m of messages) {
    if (m.role === "tool") {
      groups[groups.length - 1]?.toolResults.push(m);
      continue;
    }
    const prev = groups[groups.length - 1];
    if (m.role === "assistant" && prev?.message.role === "assistant") {
      prev.message = {
        ...m,
        content: [prev.message.content, m.content].filter(Boolean).join("\n\n"),
        tool_calls: [...prev.message.tool_calls, ...m.tool_calls],
      };
      continue;
    }
    groups.push({ message: m, toolResults: [] });
  }
  return groups;
}

function CreatedItemLinks({
  message,
  results,
  onOpenItem,
}: {
  message: DialogMessage;
  results: DialogMessage[];
  onOpenItem: (id: string, materialType: "note" | "list") => void;
}) {
  const links = message.tool_calls
    .filter((tc) => tc.name === "create_note" || tc.name === "create_list")
    .map((tc) => {
      const result = results.find((r) => r.tool_call_id === tc.id);
      if (!result) return null;
      try {
        const parsed = JSON.parse(result.content);
        if (!parsed.id || parsed.error) return null;
        return {
          id: parsed.id as string,
          title: (parsed.title as string) || "без названия",
          materialType: (tc.name === "create_list" ? "list" : "note") as "note" | "list",
        };
      } catch {
        return null;
      }
    })
    .filter((x): x is { id: string; title: string; materialType: "note" | "list" } => x !== null);

  if (links.length === 0) return null;

  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {links.map((link) => (
        <button
          key={link.id}
          onClick={() => onOpenItem(link.id, link.materialType)}
          className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
        >
          Открыть «{link.title}» <ChevronRight size={11} />
        </button>
      ))}
    </div>
  );
}

function CalendarEventLinks({ message, results }: { message: DialogMessage; results: DialogMessage[] }) {
  const events = message.tool_calls
    .filter((tc) => tc.name === "create_calendar_event")
    .map((tc) => {
      const result = results.find((r) => r.tool_call_id === tc.id);
      if (!result) return null;
      try {
        const parsed = JSON.parse(result.content);
        if (!parsed.title || !parsed.start || parsed.error) return null;
        return parsed as { title: string; start: string; end: string; all_day: boolean; location?: string; description?: string };
      } catch {
        return null;
      }
    })
    .filter((x): x is { title: string; start: string; end: string; all_day: boolean; location?: string; description?: string } => x !== null);

  if (events.length === 0) return null;

  // Google Calendar понимает публичный, документированный URL-шаблон —
  // строим его сами из уже известных данных тула, а не доверяем модели
  // написать такую ссылку текстом (та же причина, что и у create_maps_link).
  // Без "Z" в датах Google трактует время как локальное для календаря
  // открывающего — то же "floating time" поведение, что и у .ics-файла.
  function googleCalendarUrl(event: (typeof events)[number]): string {
    const fmt = (iso: string) => (event.all_day ? iso.replace(/-/g, "") : iso.replace(/[-:]/g, ""));
    const params = new URLSearchParams({
      action: "TEMPLATE",
      text: event.title,
      dates: `${fmt(event.start)}/${fmt(event.end)}`,
    });
    if (event.location) params.set("location", event.location);
    if (event.description) params.set("details", event.description);
    return `https://calendar.google.com/calendar/render?${params.toString()}`;
  }

  // Один пузырь чата может нести несколько событий сразу (агентный цикл
  // теперь склеивает весь ход в один пузырь — см. groupMessages) — плоский
  // ряд одинаково подписанных кнопок было не отличить одно от другого
  // (реальная жалоба). Подписываем каждую пару кнопок названием события и
  // ставим их в свою строку, а не всё вперемешку.
  return (
    <div className="mt-1.5 flex flex-col gap-1">
      {events.map((event, i) => {
        const icsParams = new URLSearchParams({
          title: event.title,
          start: event.start,
          end: event.end,
          all_day: String(event.all_day),
          location: event.location ?? "",
          description: event.description ?? "",
        });
        return (
          <div key={i} className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-slate-500">{event.title}:</span>
            <a
              href={googleCalendarUrl(event)}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
            >
              <CalendarPlus size={13} /> Google Календарь
            </a>
            <a
              href={`/api/calendar/event.ics?${icsParams.toString()}`}
              className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
            >
              <CalendarPlus size={13} /> Скачать .ics
            </a>
          </div>
        );
      })}
    </div>
  );
}

function MapsLinkButtons({ message, results }: { message: DialogMessage; results: DialogMessage[] }) {
  const links = message.tool_calls
    .filter((tc) => tc.name === "create_maps_link")
    .map((tc) => {
      const result = results.find((r) => r.tool_call_id === tc.id);
      if (!result) return null;
      try {
        const parsed = JSON.parse(result.content);
        if (!parsed.url || parsed.error) return null;
        return parsed as { query: string; url: string };
      } catch {
        return null;
      }
    })
    .filter((x): x is { query: string; url: string } => x !== null);

  if (links.length === 0) return null;

  // Apple Maps понимает такой же публичный URL-шаблон, как Google Maps —
  // строим его на фронтенде из уже известного query, не трогая бэкенд
  // (та же логика, что у двух кнопок календаря): пользователь хочет
  // выбирать между экосистемами, а не только Google.
  //
  // Подписываем каждую пару кнопок местом, которое она открывает, и ставим
  // в свою строку — та же причина, что у CalendarEventLinks: несколько
  // мест в одном пузыре иначе неотличимы друг от друга.
  return (
    <div className="mt-1.5 flex flex-col gap-1">
      {links.map((link, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-slate-500">{link.query}:</span>
          <a
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
          >
            <MapPin size={13} /> Google Карты
          </a>
          <a
            href={`https://maps.apple.com/?q=${encodeURIComponent(link.query)}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
          >
            <MapPin size={13} /> Apple Карты
          </a>
        </div>
      ))}
    </div>
  );
}

function ToolCallRow({ message, results }: { message: DialogMessage; results: DialogMessage[] }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="mt-1.5 space-y-1">
      {message.tool_calls.map((tc) => {
        const result = results.find((r) => r.tool_call_id === tc.id);
        return (
          <div key={tc.id} className="rounded border border-slate-200 bg-white text-xs">
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-slate-500 hover:text-slate-700"
            >
              {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              <Wrench size={12} />
              <span className="font-mono">{tc.name}</span>
            </button>
            {expanded && (
              <div className="space-y-1 break-all border-t border-slate-200 px-2 py-1.5 font-mono text-[11px] text-slate-500">
                <div>
                  <span className="text-slate-400">аргументы: </span>
                  {JSON.stringify(tc.arguments)}
                </div>
                {result && (
                  <div>
                    <span className="text-slate-400">результат: </span>
                    {result.content}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// Озвучивание — общее для всех реплик и для автоозвучивания состояние на
// уровне AssistantChat (см. playMessage/toggleSpeak ниже): без этого
// параллельные клики или клик поверх автоозвучивания накладывали два аудио
// друг на друга ("какофония" из отзыва).
function SpeakButton({
  isActive,
  isLoading,
  onClick,
}: {
  isActive: boolean;
  isLoading: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={isActive ? "Остановить" : "Озвучить"}
      className="mt-1 flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:text-slate-700"
    >
      {isLoading ? <Spinner size={12} /> : isActive ? <VolumeX size={12} /> : <Volume2 size={12} />}
    </button>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // буфер обмена недоступен (нет разрешения/не https) — молча игнорируем
        }
      }}
      title={copied ? "Скопировано" : "Скопировать"}
      className="mt-1 flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:text-slate-700"
    >
      {copied ? <Check size={12} className="text-green-600" /> : <Copy size={12} />}
    </button>
  );
}

const WIDTH_OPTIONS: { value: ContentWidth; title: string; icon: typeof AlignCenter }[] = [
  { value: "narrow", title: "Узко", icon: AlignCenter },
  { value: "wide", title: "Широко", icon: StretchHorizontal },
  { value: "full", title: "Во весь экран", icon: Maximize2 },
];

export default function AssistantChat({
  dialogId,
  onBack,
  onOpenItem,
}: {
  dialogId: string;
  onBack: () => void;
  onOpenItem: (id: string, materialType: "note" | "list") => void;
}) {
  const { data: dialog } = useDialog(dialogId);
  const sendMessage = useSendDialogMessage(dialogId);
  const deleteMessage = useDeleteDialogMessage(dialogId);
  const updateItem = useUpdateItem();
  const qc = useQueryClient();
  const [deletingMessageId, setDeletingMessageId] = useState<string | null>(null);
  const [renamingTitle, setRenamingTitle] = useState(false);
  const [autoSpeak, setAutoSpeakState] = useState(() => uiStorage.getAutoSpeak());
  const speakMutation = useSpeak();
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const speechRequestIdRef = useRef(0);
  const [activeSpeechId, setActiveSpeechId] = useState<string | null>(null);
  const autoSpeakBaselineRef = useRef<{ dialogId: string; lastId: string | null } | null>(null);
  const [pendingUserText, setPendingUserText] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const [input, setInputState] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [silenceProgress, setSilenceProgress] = useState(0);
  const [chatWidth, setChatWidth] = useState<ContentWidth>(() => uiStorage.getChatContentWidth());
  const bottomRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const micPulseRef = useRef<HTMLSpanElement>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number | null>(null);
  const silenceStartRef = useRef<number | null>(null);
  // База (что было в поле до записи) + закоммиченные сегменты + текущий
  // partial — refs, а не state: их читает rAF-цикл и WebSocket-колбэки вне
  // React-рендера, там state был бы протухшим замыканием.
  const baseTextRef = useRef("");
  const committedRef = useRef("");
  const partialRef = useRef("");
  const inputRef = useRef("");

  function setInput(value: string) {
    inputRef.current = value;
    setInputState(value);
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [dialog?.messages.length, sendMessage.isPending, pendingUserText]);

  useEffect(() => stopStreaming, []);

  // Автоувеличение поля ввода — надиктованный длинный текст должен быть
  // виден целиком, а не скроллиться внутри однострочной полоски.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  function changeChatWidth(width: ContentWidth) {
    setChatWidth(width);
    uiStorage.setChatContentWidth(width);
  }

  function toggleAutoSpeak() {
    setAutoSpeakState((v) => {
      const next = !v;
      uiStorage.setAutoSpeak(next);
      return next;
    });
  }

  // Единая точка воспроизведения: обрывает текущее аудио перед стартом
  // нового — раньше второй клик (или клик поверх автоозвучивания) запускал
  // второе аудио поверх первого без остановки исходного ("какофония" из
  // отзыва).
  function stopSpeaking() {
    // Инвалидирует и любой ещё летящий запрос озвучивания (см. playMessage) —
    // без этого остановка во время загрузки аудио (запрос к Palabra занимает
    // секунду-другую) ничего не отменяла: запрос долетал и всё равно
    // запускал проигрывание, выглядело как "перезапуск" вместо остановки.
    speechRequestIdRef.current += 1;
    currentAudioRef.current?.pause();
    currentAudioRef.current = null;
    setActiveSpeechId(null);
  }

  async function playMessage(id: string, text: string) {
    stopSpeaking();
    const requestId = speechRequestIdRef.current;
    setActiveSpeechId(id);
    try {
      const blob = await speakMutation.mutateAsync(text);
      if (speechRequestIdRef.current !== requestId) return; // отменили, пока грузили
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.onended = () => {
        URL.revokeObjectURL(url);
        setActiveSpeechId((cur) => (cur === id ? null : cur));
      };
      currentAudioRef.current = audio;
      await audio.play();
    } catch {
      if (speechRequestIdRef.current === requestId) {
        setActiveSpeechId((cur) => (cur === id ? null : cur));
      }
    }
  }

  function toggleSpeak(id: string, text: string) {
    if (activeSpeechId === id) {
      stopSpeaking();
    } else {
      playMessage(id, text);
    }
  }

  useEffect(() => stopSpeaking, [dialogId]);

  // Автоозвучивание: при переключении диалога сначала просто запоминаем,
  // какое сообщение последнее (уже прочитанная история не озвучивается),
  // и только следующие за этим новые ответы ассистента проигрываются сами.
  useEffect(() => {
    if (!dialog) return;
    const lastMsg = dialog.messages[dialog.messages.length - 1];
    const currentLastId = lastMsg?.id ?? null;

    if (!autoSpeakBaselineRef.current || autoSpeakBaselineRef.current.dialogId !== dialogId) {
      autoSpeakBaselineRef.current = { dialogId, lastId: currentLastId };
      return;
    }
    if (autoSpeakBaselineRef.current.lastId === currentLastId) return;
    autoSpeakBaselineRef.current.lastId = currentLastId;

    if (autoSpeak && lastMsg && lastMsg.role === "assistant" && lastMsg.content) {
      playMessage(lastMsg.id, lastMsg.content);
    }
  }, [dialog, dialogId, autoSpeak]);

  async function submitContent(content: string) {
    if (!content || sendMessage.isPending) return;
    setInput("");
    // Оптимистично показываем реплику сразу — агентный цикл на сервере
    // может занять много секунд (несколько вызовов инструментов подряд),
    // и без этого пользователь не видел, что вообще отправил сообщение.
    setPendingUserText(content);
    const controller = new AbortController();
    abortControllerRef.current = controller;
    try {
      await sendMessage.mutateAsync({ content, signal: controller.signal });
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        throw err;
      }
    } finally {
      setPendingUserText(null);
      abortControllerRef.current = null;
    }
  }

  function cancelSend() {
    abortControllerRef.current?.abort();
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (isRecording) stopStreaming();
    await submitContent(input.trim());
  }

  async function sendQuickReply(text: string) {
    if (isRecording) stopStreaming();
    await submitContent(text);
  }

  function updateInputDisplay(partial: string) {
    partialRef.current = partial;
    const parts = [baseTextRef.current, committedRef.current, partial].filter(Boolean);
    setInput(parts.join(" "));
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

  function setMicPulse(volume: number) {
    const el = micPulseRef.current;
    if (!el) return;
    const level = Math.min(volume * 4, 1);
    el.style.transform = `scale(${1 + level * 0.7})`;
    el.style.opacity = String(0.25 + level * 0.75);
  }

  async function autoSend() {
    const content = inputRef.current.trim();
    stopStreaming();
    await submitContent(content);
  }

  function startVisualizerLoop() {
    const analyser = analyserRef.current;
    if (!analyser) return;
    const data = new Uint8Array(analyser.fftSize);
    let lastProgressUpdate = 0;

    const tick = (now: number) => {
      if (!analyserRef.current) return;
      analyser.getByteTimeDomainData(data);

      let sumSquares = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sumSquares += v * v;
      }
      const volume = Math.sqrt(sumSquares / data.length);

      drawWaveform(data);
      setMicPulse(volume);

      const hasContent = committedRef.current.length > 0 || partialRef.current.length > 0;
      if (hasContent) {
        if (volume > SILENCE_VOLUME_THRESHOLD) {
          silenceStartRef.current = null;
          if (now - lastProgressUpdate > 100) {
            setSilenceProgress(0);
            lastProgressUpdate = now;
          }
        } else {
          if (silenceStartRef.current === null) silenceStartRef.current = now;
          const elapsed = now - silenceStartRef.current;
          const progress = Math.min(1, elapsed / SILENCE_AUTO_SEND_MS);
          if (now - lastProgressUpdate > 100) {
            setSilenceProgress(progress);
            lastProgressUpdate = now;
          }
          if (progress >= 1) {
            autoSend();
            return;
          }
        }
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    rafRef.current = requestAnimationFrame(tick);
  }

  function stopStreaming() {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    analyserRef.current = null;
    silenceStartRef.current = null;
    setSilenceProgress(0);
    wsRef.current?.close();
    wsRef.current = null;
    processorRef.current?.disconnect();
    processorRef.current = null;
    sourceRef.current?.disconnect();
    sourceRef.current = null;
    audioContextRef.current?.close();
    audioContextRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setIsRecording(false);
  }

  async function startStreaming() {
    setVoiceError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const audioContext = new AudioContext({ sampleRate: 16000 });

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(
        `${protocol}//${window.location.host}/api/voice/asr-stream?language=ru&sample_rate=${audioContext.sampleRate}`,
      );

      baseTextRef.current = input;
      committedRef.current = "";
      partialRef.current = "";

      ws.onopen = () => {
        const source = audioContext.createMediaStreamSource(stream);
        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 2048;

        processor.onaudioprocess = (e) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(floatTo16BitPCM(e.inputBuffer.getChannelData(0)));
          }
        };

        // Тишина на выходе: граф должен доходить до destination, чтобы
        // ScriptProcessorNode вообще получал колбэки, но озвучивать
        // собственный микрофон пользователю не нужно.
        const mute = audioContext.createGain();
        mute.gain.value = 0;
        source.connect(processor);
        processor.connect(mute);
        mute.connect(audioContext.destination);
        source.connect(analyser);

        sourceRef.current = source;
        processorRef.current = processor;
        analyserRef.current = analyser;
        startVisualizerLoop();
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          if (msg.message_type === "transcription") {
            const text = msg.segment?.text ?? "";
            if (msg.is_eos) {
              committedRef.current = [committedRef.current, text].filter(Boolean).join(" ");
              updateInputDisplay("");
            } else {
              updateInputDisplay(text);
            }
          } else if (msg.message_type === "error") {
            setVoiceError(msg.data?.desc || "Голосовой ввод недоступен");
            stopStreaming();
          }
        } catch {
          // нераспознанное сообщение — игнорируем
        }
      };

      ws.onerror = () => setVoiceError("Обрыв голосового стрима");

      wsRef.current = ws;
      audioContextRef.current = audioContext;
      streamRef.current = stream;
      setIsRecording(true);
    } catch {
      setVoiceError("Нет доступа к микрофону");
    }
  }

  function toggleRecording() {
    if (isRecording) {
      stopStreaming();
    } else {
      startStreaming();
    }
  }

  const groups = groupMessages(dialog?.messages ?? []);

  async function handleExport(format: "md" | "html") {
    const title = dialog?.title || "Диалог";
    const filename = sanitizeFilename(title);
    const turns = groups.filter(({ message }) => (message.role === "user" || message.role === "assistant") && message.content);

    if (format === "md") {
      const parts = turns.map(
        ({ message }) => `**${message.role === "user" ? "Пользователь" : "Ассистент"}:**\n\n${message.content}`,
      );
      downloadFile(`${filename}.md`, `# ${title}\n\n${parts.join("\n\n---\n\n")}`, "text/markdown");
    } else {
      const partsHtml = turns.map(({ message }) => {
        const body =
          message.role === "assistant"
            ? ReactDOMServer.renderToStaticMarkup(
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{message.content}</ReactMarkdown>,
              )
            : `<p>${message.content.replace(/</g, "&lt;").replace(/\n/g, "<br>")}</p>`;
        return `<p><strong>${message.role === "user" ? "Пользователь" : "Ассистент"}:</strong></p>${body}`;
      });
      downloadFile(`${filename}.html`, wrapHtmlDocument(title, partsHtml.join("<hr>")), "text/html");
    }
  }

  const widthClass =
    chatWidth === "narrow" ? "mx-auto max-w-3xl" : chatWidth === "wide" ? "mx-auto max-w-5xl" : "max-w-none";

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1 border-b p-3">
        <button
          onClick={onBack}
          className="-ml-1 flex h-8 w-8 shrink-0 items-center justify-center text-slate-500 md:hidden"
        >
          <ChevronLeft size={18} />
        </button>
        <div className="flex min-w-0 flex-1 items-center gap-1">
          <span className="truncate text-sm font-medium text-slate-900">{dialog?.title || "Диалог"}</span>
          <button
            onClick={() => setRenamingTitle(true)}
            title="Переименовать диалог"
            className="flex h-6 w-6 shrink-0 items-center justify-center text-slate-300 hover:text-slate-700"
          >
            <Pencil size={12} />
          </button>
        </div>
        <button
          onClick={toggleAutoSpeak}
          title={autoSpeak ? "Не озвучивать ответы автоматически" : "Озвучивать ответы автоматически"}
          className={`flex h-7 w-7 shrink-0 items-center justify-center rounded ${
            autoSpeak ? "bg-slate-200 text-slate-900" : "text-slate-400 hover:bg-slate-100"
          }`}
        >
          {autoSpeak ? <Volume2 size={14} /> : <VolumeX size={14} />}
        </button>
        <div className="hidden shrink-0 items-center gap-0.5 md:flex">
          {WIDTH_OPTIONS.map(({ value, title, icon: Icon }) => (
            <button
              key={value}
              title={title}
              onClick={() => changeChatWidth(value)}
              className={`flex h-7 w-7 items-center justify-center rounded ${
                chatWidth === value ? "bg-slate-200 text-slate-900" : "text-slate-400 hover:bg-slate-100"
              }`}
            >
              <Icon size={14} />
            </button>
          ))}
        </div>
        <div className="ml-1 shrink-0">
          <ExportMenu onExport={handleExport} />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className={`space-y-3 ${widthClass}`}>
          {groups.length === 0 && (
            <div className="flex h-full items-center justify-center text-center text-sm text-slate-400">
              Спросите что-нибудь о своих заметках или попросите создать новую
            </div>
          )}
          {groups.map(({ message, toolResults }, index) => (
            <div
              key={message.id}
              className={`flex items-start gap-1 ${message.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {message.role === "assistant" && (
                <button
                  onClick={() => setDeletingMessageId(message.id)}
                  title="Удалить"
                  className="mt-2 flex h-6 w-6 shrink-0 items-center justify-center text-slate-300 hover:text-red-600"
                >
                  <Trash2 size={13} />
                </button>
              )}
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                  message.role === "user" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-900"
                }`}
              >
                {message.content &&
                  (message.role === "assistant" ? (
                    <div className="tiptap">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>{message.content}</ReactMarkdown>
                    </div>
                  ) : (
                    <div className="whitespace-pre-wrap">{message.content}</div>
                  ))}
                {message.tool_calls.length > 0 && <ToolCallRow message={message} results={toolResults} />}
                {message.tool_calls.length > 0 && (
                  <CreatedItemLinks message={message} results={toolResults} onOpenItem={onOpenItem} />
                )}
                {message.tool_calls.length > 0 && <CalendarEventLinks message={message} results={toolResults} />}
                {message.tool_calls.length > 0 && <MapsLinkButtons message={message} results={toolResults} />}
                {message.role === "assistant" && message.content && (
                  <div className="flex items-center gap-0.5">
                    <SpeakButton
                      isActive={activeSpeechId === message.id}
                      isLoading={speakMutation.isPending && activeSpeechId === message.id}
                      onClick={() => toggleSpeak(message.id, message.content)}
                    />
                    <CopyButton text={message.content} />
                  </div>
                )}
                {/* Чипы актуальны только у последней реплики — старые из
                    прошлого хода кликать уже не в контексте. */}
                {message.role === "assistant" &&
                  index === groups.length - 1 &&
                  !sendMessage.isPending &&
                  message.suggested_replies.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {message.suggested_replies.map((option) => (
                        <button
                          key={option}
                          onClick={() => sendQuickReply(option)}
                          className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs text-slate-700 hover:border-slate-400 hover:bg-slate-50"
                        >
                          {option}
                        </button>
                      ))}
                    </div>
                  )}
              </div>
              {message.role === "user" && (
                <button
                  onClick={() => setDeletingMessageId(message.id)}
                  title="Удалить"
                  className="mt-2 flex h-6 w-6 shrink-0 items-center justify-center text-slate-300 hover:text-red-600"
                >
                  <Trash2 size={13} />
                </button>
              )}
            </div>
          ))}
          {pendingUserText && (
            <div className="flex justify-end">
              <div className="max-w-[85%] rounded-lg bg-slate-900 px-3 py-2 text-sm text-white opacity-60">
                <div className="whitespace-pre-wrap">{pendingUserText}</div>
              </div>
            </div>
          )}
          {sendMessage.isPending && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-500">
                <Spinner size={14} /> Ассистент думает…
                <button
                  onClick={cancelSend}
                  className="ml-1 rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-200"
                >
                  Отменить
                </button>
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      {isRecording && (
        <div className="border-t bg-slate-50 px-3 py-1.5">
          <canvas ref={canvasRef} width={600} height={28} className="h-7 w-full" />
        </div>
      )}

      {voiceError && <div className="border-t bg-amber-50 px-3 py-1.5 text-xs text-amber-700">{voiceError}</div>}

      <div className="border-t p-3">
        <form onSubmit={handleSubmit} className={`flex gap-2 ${widthClass}`}>
          <button
            type="button"
            onClick={toggleRecording}
            title={isRecording ? "Остановить запись" : "Голосовой ввод"}
            className={`relative flex shrink-0 items-center justify-center overflow-hidden rounded border px-3 py-2 text-sm ${
              isRecording ? "border-red-300 bg-red-50 text-red-600" : "text-slate-500 hover:bg-slate-100"
            }`}
          >
            {isRecording && (
              <span
                ref={micPulseRef}
                className="pointer-events-none absolute inset-0 rounded bg-red-300"
                style={{ opacity: 0.25 }}
              />
            )}
            <span className="relative">{isRecording ? <Square size={14} /> : <Mic size={14} />}</span>
          </button>
          <div className="relative flex-1">
            {isRecording && silenceProgress > 0 && (
              <div
                className="pointer-events-none absolute inset-y-0 left-0 rounded bg-emerald-100 transition-[width]"
                style={{ width: `${silenceProgress * 100}%` }}
              />
            )}
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e: KeyboardEvent<HTMLTextAreaElement>) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  if (isRecording) stopStreaming();
                  submitContent(input.trim());
                }
              }}
              placeholder="Написать ассистенту…"
              disabled={sendMessage.isPending}
              rows={1}
              className="relative w-full resize-none overflow-y-auto rounded border bg-transparent px-3 py-2 text-sm disabled:opacity-50"
            />
          </div>
          <button
            type="submit"
            disabled={sendMessage.isPending || !input.trim()}
            className="flex shrink-0 items-center justify-center rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            {sendMessage.isPending ? <Spinner size={14} className="text-white" /> : "Отправить"}
          </button>
        </form>
      </div>

      {deletingMessageId && (
        <ConfirmDialog
          title="Удалить это сообщение? Действие необратимо."
          danger
          onConfirm={() => {
            deleteMessage.mutate(deletingMessageId);
            setDeletingMessageId(null);
          }}
          onCancel={() => setDeletingMessageId(null)}
        />
      )}

      {renamingTitle && dialog && (
        <PromptDialog
          title="Название диалога"
          initialValue={dialog.title}
          onConfirm={async (value) => {
            const trimmed = value.trim();
            if (trimmed && trimmed !== dialog.title) {
              await updateItem.mutateAsync({ id: dialog.id, title: trimmed });
              qc.setQueryData(["dialog", dialogId], { ...dialog, title: trimmed });
              qc.invalidateQueries({ queryKey: ["dialogs", dialog.space_id] });
            }
            setRenamingTitle(false);
          }}
          onCancel={() => setRenamingTitle(false)}
        />
      )}
    </div>
  );
}

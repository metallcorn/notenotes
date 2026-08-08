import { useEffect, useState } from "react";
import { Send, Trash2, X } from "lucide-react";
import {
  useDeleteMemory,
  useMe,
  useMemories,
  useSkills,
  useTelegramLinkCode,
  useTelegramStatus,
  useTelegramUnlink,
  useUpdateAutoProcessUploads,
  useUpdateCustomInstructions,
  useUpdateDisabledTools,
  useUpdateTtsVoice,
} from "../api/hooks";
import { DEFAULT_MEDIA_CACHE_LIMIT_MB, getMediaCacheLimitBytes, setMediaCacheLimitMb } from "../lib/offlineSettings";
import Spinner from "./Spinner";

const VOICE_PRESETS = [
  { value: "default_low", label: "Мужской" },
  { value: "default_high", label: "Женский" },
];

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const { data: me } = useMe();
  const { data: memories, isLoading } = useMemories();
  const { data: skills, isLoading: skillsLoading } = useSkills();
  const deleteMemory = useDeleteMemory();
  const updateInstructions = useUpdateCustomInstructions();
  const updateDisabledTools = useUpdateDisabledTools();
  const updateTtsVoice = useUpdateTtsVoice();
  const updateAutoProcessUploads = useUpdateAutoProcessUploads();
  const { data: telegramStatus } = useTelegramStatus();
  const telegramLinkCode = useTelegramLinkCode();
  const telegramUnlink = useTelegramUnlink();

  const [instructions, setInstructions] = useState(me?.custom_instructions ?? "");
  const [saved, setSaved] = useState(false);
  const [customVoiceId, setCustomVoiceId] = useState("");
  const [telegramDeepLink, setTelegramDeepLink] = useState<string | null>(null);
  const [mediaCacheLimitMb, setMediaCacheLimitMbState] = useState(DEFAULT_MEDIA_CACHE_LIMIT_MB);
  const [mediaCacheSaved, setMediaCacheSaved] = useState(false);

  useEffect(() => {
    getMediaCacheLimitBytes().then((bytes) => setMediaCacheLimitMbState(bytes / (1024 * 1024)));
  }, []);

  async function handleSaveMediaCacheLimit() {
    await setMediaCacheLimitMb(mediaCacheLimitMb);
    setMediaCacheSaved(true);
    setTimeout(() => setMediaCacheSaved(false), 1500);
  }

  const currentVoice = me?.tts_voice ?? "default_low";
  const isPresetVoice = VOICE_PRESETS.some((v) => v.value === currentVoice);

  async function handleSave() {
    await updateInstructions.mutateAsync(instructions);
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  }

  function toggleSkill(skill: { name: string; enabled: boolean }) {
    const disabled = new Set((skills ?? []).filter((s) => !s.enabled).map((s) => s.name));
    if (skill.enabled) {
      disabled.add(skill.name);
    } else {
      disabled.delete(skill.name);
    }
    updateDisabledTools.mutate([...disabled]);
  }

  const toggleableSkills = (skills ?? []).filter((s) => s.toggleable);
  const coreSkills = (skills ?? []).filter((s) => !s.toggleable);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-lg bg-white shadow-xl"
      >
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="text-sm font-medium text-slate-900">Настройки ассистента</div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center text-slate-400 hover:text-slate-700"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-slate-900">Дополнительные инструкции</div>
            <div className="mb-2 text-xs text-slate-400">
              Добавляются к базовым инструкциям ассистента, а не заменяют их — так безопасность и работа
              инструментов не ломаются, даже если тут написать что-то странное.
            </div>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={4}
              placeholder="Например: обращайся на «ты», предпочитаю короткие ответы…"
              className="w-full rounded border px-3 py-2 text-sm"
            />
            <button
              onClick={handleSave}
              disabled={updateInstructions.isPending}
              className="mt-2 flex items-center gap-2 rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
            >
              {updateInstructions.isPending ? (
                <Spinner size={14} className="text-white" />
              ) : saved ? (
                "Сохранено"
              ) : (
                "Сохранить"
              )}
            </button>
          </div>

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-slate-900">Умения ассистента</div>
            <div className="mb-2 text-xs text-slate-400">Что ассистент умеет делать в этом диалоге.</div>
            {skillsLoading && <div className="text-sm text-slate-400">Загрузка…</div>}
            <ul className="space-y-1">
              {toggleableSkills.map((skill) => (
                <li key={skill.name} className="flex items-center justify-between gap-2 rounded border px-2 py-1.5">
                  <div className="min-w-0">
                    <div className="text-sm text-slate-900">{skill.label}</div>
                    <div className="truncate text-xs text-slate-400">{skill.description}</div>
                  </div>
                  <button
                    role="switch"
                    aria-checked={skill.enabled}
                    onClick={() => toggleSkill(skill)}
                    disabled={updateDisabledTools.isPending}
                    className={`flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors disabled:opacity-50 ${
                      skill.enabled ? "justify-end bg-slate-900" : "justify-start bg-slate-200"
                    }`}
                  >
                    <span className="h-4 w-4 rounded-full bg-white shadow" />
                  </button>
                </li>
              ))}
            </ul>
            {coreSkills.length > 0 && (
              <div className="mt-2 text-xs text-slate-400">
                Всегда включено: {coreSkills.map((s) => s.label).join(", ")}.
              </div>
            )}
          </div>

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-slate-900">Голос озвучивания</div>
            <div className="mb-2 text-xs text-slate-400">
              У Palabra нет «стилей» — только два готовых голоса и возможность указать свой voice_id с Palabra
              Platform.
            </div>
            <div className="flex gap-1.5">
              {VOICE_PRESETS.map((preset) => (
                <button
                  key={preset.value}
                  onClick={() => updateTtsVoice.mutate(preset.value)}
                  disabled={updateTtsVoice.isPending}
                  className={`rounded border px-3 py-1.5 text-sm disabled:opacity-50 ${
                    currentVoice === preset.value
                      ? "border-slate-900 bg-slate-900 text-white"
                      : "border-slate-300 text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <input
                value={customVoiceId}
                onChange={(e) => setCustomVoiceId(e.target.value)}
                placeholder="Свой voice_id с Palabra Platform"
                className="w-full rounded border px-3 py-1.5 text-sm"
              />
              <button
                onClick={() => customVoiceId.trim() && updateTtsVoice.mutate(customVoiceId.trim())}
                disabled={updateTtsVoice.isPending || !customVoiceId.trim()}
                className="shrink-0 rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Применить
              </button>
            </div>
            {!isPresetVoice && (
              <div className="mt-1 text-xs text-slate-400">Сейчас используется свой голос: {currentVoice}</div>
            )}
          </div>

          <div className="mb-6">
            <div className="flex items-center justify-between gap-2 rounded border px-2 py-1.5">
              <div className="min-w-0">
                <div className="text-sm text-slate-900">Обработка загруженных файлов</div>
                <div className="text-xs text-slate-400">
                  Автоматически распознавать текст в картинках, видео и PDF при загрузке — не только по кнопке
                  «Распознать».
                </div>
              </div>
              <button
                role="switch"
                aria-checked={me?.auto_process_uploads ?? true}
                onClick={() => updateAutoProcessUploads.mutate(!(me?.auto_process_uploads ?? true))}
                disabled={updateAutoProcessUploads.isPending}
                className={`flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors disabled:opacity-50 ${
                  me?.auto_process_uploads ?? true ? "justify-end bg-slate-900" : "justify-start bg-slate-200"
                }`}
              >
                <span className="h-4 w-4 rounded-full bg-white shadow" />
              </button>
            </div>
          </div>

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-slate-900">Telegram</div>
            <div className="mb-2 text-xs text-slate-400">
              Подключите бота — присылайте ему текст, фото, голосовые и видео, они автоматически станут заметками
              в отдельном личном спейсе «Telegram» (с авто-тегами и OCR, как и везде).
            </div>
            {telegramStatus?.linked ? (
              <div className="flex items-center justify-between gap-2 rounded border px-3 py-2 text-sm">
                <span className="text-slate-700">Подключено ✅</span>
                <button
                  onClick={() => telegramUnlink.mutate()}
                  disabled={telegramUnlink.isPending}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                >
                  {telegramUnlink.isPending ? <Spinner size={12} /> : "Отключить"}
                </button>
              </div>
            ) : telegramDeepLink ? (
              <a
                href={telegramDeepLink}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 rounded bg-sky-500 px-3 py-1.5 text-sm text-white hover:bg-sky-600"
              >
                <Send size={14} />
                Открыть в Telegram
              </a>
            ) : (
              <button
                onClick={() =>
                  telegramLinkCode
                    .mutateAsync()
                    .then((r) => setTelegramDeepLink(r.deep_link))
                    .catch(() => {})
                }
                disabled={telegramLinkCode.isPending}
                className="flex items-center gap-2 rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
              >
                {telegramLinkCode.isPending && <Spinner size={14} className="text-white" />}
                Подключить
              </button>
            )}
            {telegramLinkCode.isError && (
              <div className="mt-1 text-xs text-red-600">Telegram-бот пока не настроен на сервере.</div>
            )}
          </div>

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-slate-900">Офлайн</div>
            <div className="mb-2 text-xs text-slate-400">
              Заметки, которые уже открывались, доступны без интернета всегда. Картинки и файлы — только если
              меньше этого размера (действует на новые загрузки, не пересчитывает уже закэшированное).
            </div>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                step={1}
                value={mediaCacheLimitMb}
                onChange={(e) => setMediaCacheLimitMbState(Number(e.target.value))}
                className="w-24 rounded border px-3 py-1.5 text-sm"
              />
              <span className="text-sm text-slate-500">МБ</span>
              <button
                onClick={handleSaveMediaCacheLimit}
                className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
              >
                {mediaCacheSaved ? "Сохранено" : "Сохранить"}
              </button>
            </div>
          </div>

          <div>
            <div className="mb-1 text-sm font-medium text-slate-900">Память ассистента</div>
            <div className="mb-2 text-xs text-slate-400">
              Факты, которые ассистент запомнил между диалогами — например, что означают твои личные
              обозначения папок.
            </div>
            {isLoading && <div className="text-sm text-slate-400">Загрузка…</div>}
            {!isLoading && (memories ?? []).length === 0 && (
              <div className="text-sm text-slate-400">Пока ничего не запомнено</div>
            )}
            <ul className="space-y-1">
              {(memories ?? []).map((m) => (
                <li key={m.id} className="flex items-start justify-between gap-2 rounded border px-2 py-1.5 text-sm">
                  <span className="flex-1">{m.content}</span>
                  <button
                    onClick={() => deleteMemory.mutate(m.id)}
                    title="Удалить"
                    className="flex h-6 w-6 shrink-0 items-center justify-center text-slate-300 hover:text-red-600"
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

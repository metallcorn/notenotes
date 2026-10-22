import { useEffect, useRef, useState } from "react";
import { Bot, Check, ChevronLeft, ChevronRight, Copy, Plug, Plus, Send, Settings2, Share2, Trash2, X } from "lucide-react";
import { applyTheme } from "../lib/theme";
import { uiStorage, type Theme } from "../lib/storage";
import { useMediaQuery } from "../lib/useMediaQuery";
import { t } from "../i18n";
import {
  useAddMemory,
  useAddOwnMailAddress,
  useCreateInviteCode,
  useDeleteMemory,
  useDisableMailInbox,
  useGenerateMailAddress,
  useInviteCodes,
  useMailStatus,
  useLogout,
  useMe,
  useMemories,
  useRegenerateMailAddress,
  useRemoveOwnMailAddress,
  useSkills,
  useTelegramLinkCode,
  useTelegramStatus,
  useTelegramUnlink,
  useUpdateAutoProcessUploads,
  useUpdateCustomInstructions,
  useUpdateDisabledTools,
  useUpdateLlmProvider,
  useUpdateTimezone,
  useUpdateTtsVoice,
} from "../api/hooks";
import { DEFAULT_MEDIA_CACHE_LIMIT_MB, getMediaCacheLimitBytes, setMediaCacheLimitMb } from "../lib/offlineSettings";
import DigestSettings from "./DigestSettings";
import McpSettings from "./McpSettings";
import { isPushSupported, usePushSubscription } from "../lib/usePushSubscription";
import Spinner from "./Spinner";

const SECTIONS = [
  { key: "assistant", label: "Ассистент", icon: Bot },
  { key: "channels", label: "Каналы", icon: Share2 },
  { key: "connect", label: "Подключения", icon: Plug },
  { key: "app", label: "Приложение", icon: Settings2 },
] as const;

type SectionKey = (typeof SECTIONS)[number]["key"];

const VOICE_PRESETS = [
  { value: "default_low", label: "Мужской" },
  { value: "default_high", label: "Женский" },
];

const LLM_PROVIDERS = [
  { value: "", label: "По умолчанию" },
  { value: "mistral", label: "Mistral" },
  { value: "gemini", label: "Gemini Flash" },
  // На бесплатном тарифе Groq не работает: наш запрос (схемы тулов +
  // промпт) ~12800 токенов при лимите 8000 TPM — 413 на каждый вызов.
  // См. подробности в core/config.py::groq_model. Оставляем в списке для
  // платного тарифа, но честно помечаем.
  { value: "groq", label: "Groq (нужен платный тариф)" },
];

// Просто удобные подсказки в datalist, не полный список ~600 IANA-имён —
// сервер валидирует по zoneinfo.available_timezones() в любом случае,
// можно ввести и любое другое корректное имя вручную.
const COMMON_TIMEZONES = [
  "Europe/Warsaw",
  "Europe/Moscow",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Kyiv",
  "Asia/Istanbul",
  "Asia/Dubai",
  "UTC",
];

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const { data: me } = useMe();
  const { data: memories, isLoading } = useMemories();
  const { data: skills, isLoading: skillsLoading } = useSkills();
  const deleteMemory = useDeleteMemory();
  const addMemory = useAddMemory();
  const updateInstructions = useUpdateCustomInstructions();
  const updateDisabledTools = useUpdateDisabledTools();
  const updateTtsVoice = useUpdateTtsVoice();
  const updateLlmProvider = useUpdateLlmProvider();
  const updateTimezone = useUpdateTimezone();
  const updateAutoProcessUploads = useUpdateAutoProcessUploads();
  const pushSubscription = usePushSubscription();
  const { data: telegramStatus } = useTelegramStatus();
  const telegramLinkCode = useTelegramLinkCode();
  const telegramUnlink = useTelegramUnlink();
  const { data: inviteCodes } = useInviteCodes();
  const createInviteCode = useCreateInviteCode();
  const { data: mailStatus } = useMailStatus();
  const generateMailAddress = useGenerateMailAddress();
  const regenerateMailAddress = useRegenerateMailAddress();
  const disableMailInbox = useDisableMailInbox();
  const addOwnMailAddress = useAddOwnMailAddress();
  const removeOwnMailAddress = useRemoveOwnMailAddress();

  const [instructions, setInstructions] = useState(me?.custom_instructions ?? "");
  const [timezoneInput, setTimezoneInput] = useState(me?.timezone ?? "Europe/Warsaw");
  const [saved, setSaved] = useState(false);
  const [customVoiceId, setCustomVoiceId] = useState("");
  const [telegramDeepLink, setTelegramDeepLink] = useState<string | null>(null);
  const [copiedCodeId, setCopiedCodeId] = useState<string | null>(null);
  const [mailCopied, setMailCopied] = useState(false);
  const [newOwnAddress, setNewOwnAddress] = useState("");
  const [mediaCacheLimitMb, setMediaCacheLimitMbState] = useState(DEFAULT_MEDIA_CACHE_LIMIT_MB);
  const [mediaCacheSaved, setMediaCacheSaved] = useState(false);
  const [newMemoryText, setNewMemoryText] = useState("");

  function handleAddMemory() {
    const text = newMemoryText.trim();
    if (!text || addMemory.isPending) return;
    addMemory.mutate(text);
    setNewMemoryText("");
  }

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

  // Телефон (макет «Настройки», 21.10): экран целиком, сначала корневой
  // список разделов с темой и «Выйти», раздел открывается с кнопкой
  // «назад». На десктопе — как раньше, модалка с колонкой разделов.
  const isPhone = useMediaQuery("(max-width: 639px)");
  const [phoneSection, setPhoneSection] = useState<SectionKey | null>(null);
  const [desktopSection, setDesktopSection] = useState<SectionKey>("assistant");
  const active: SectionKey = isPhone ? (phoneSection ?? "assistant") : desktopSection;
  const setActive = (key: SectionKey) => (isPhone ? setPhoneSection(key) : setDesktopSection(key));
  const showRoot = isPhone && phoneSection === null;
  const logout = useLogout();
  const [theme, setThemeState] = useState<Theme>(() => uiStorage.getTheme());
  function pickTheme(next: Theme) {
    uiStorage.setTheme(next);
    applyTheme(next);
    setThemeState(next);
  }
  // Предыдущая секция — только чтобы знать направление. В ref, не в
  // state: от него не должен зависеть рендер, иначе лишний проход.
  const previousSection = useRef<SectionKey>("assistant");
  const order = (key: SectionKey) => SECTIONS.findIndex((s) => s.key === key);
  const sectionSlide =
    order(active) >= order(previousSection.current) ? "tab-slide-forward" : "tab-slide-back";
  useEffect(() => {
    previousSection.current = active;
  }, [active]);
  const SUBTITLES: Record<SectionKey, string> = {
    assistant: t("settings.sub.assistant"),
    channels: t("settings.sub.channels"),
    connect: t("settings.sub.connect"),
    app: t("settings.sub.app"),
  };

  const toggleableSkills = (skills ?? []).filter((s) => s.toggleable);
  const coreSkills = (skills ?? []).filter((s) => !s.toggleable);

  return (
    <div className="modal-in fixed inset-0 z-50 flex items-center justify-center bg-black/40 sm:p-4" onClick={onClose}>
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex h-full w-full flex-col overflow-hidden bg-app shadow-xl sm:h-auto sm:max-h-[88vh] sm:max-w-3xl sm:rounded-3xl sm:bg-surface"
        style={{ paddingTop: "var(--safe-top)" }}
      >
        <div className="flex items-center gap-2 px-3 py-3 sm:justify-between sm:px-5 sm:py-4">
          {isPhone && (
            <button
              onClick={() => (phoneSection ? setPhoneSection(null) : onClose())}
              aria-label={t("nav.back")}
              className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-surface text-primary shadow-card"
            >
              <ChevronLeft size={20} strokeWidth={2.4} />
            </button>
          )}
          <div className="min-w-0 flex-1 text-xl font-extrabold tracking-tight text-primary">
            {showRoot ? "Настройки" : isPhone ? SECTIONS.find((x) => x.key === active)?.label : "Настройки"}
          </div>
          {!isPhone && (
            <button
              onClick={onClose}
              aria-label="Закрыть"
              className="flex h-10 w-10 items-center justify-center rounded-xl bg-muted text-primary hover:bg-muted-hover"
            >
              <X size={18} />
            </button>
          )}
        </div>

        {showRoot ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-[max(20px,var(--safe-bottom))]">
            <div className="flex items-center gap-3.5 px-1">
              <span className="flex h-[60px] w-[60px] shrink-0 items-center justify-center rounded-2xl bg-nav text-2xl font-extrabold text-lime">
                {(me?.name || "?").slice(0, 1).toUpperCase()}
              </span>
              <div className="min-w-0">
                <div className="truncate text-[22px] font-extrabold tracking-tight text-primary">{me?.name}</div>
                <div className="truncate text-[13px] font-semibold text-subtle">
                  @{me?.username}
                  {me?.timezone ? ` · ${me.timezone}` : ""}
                </div>
              </div>
            </div>
            <div className="mt-4 rounded-2xl bg-surface p-3.5 shadow-card">
              <div className="text-[11px] font-extrabold uppercase tracking-wider text-subtle">{t("settings.theme")}</div>
              <div role="radiogroup" aria-label={t("settings.theme")} className="mt-2.5 grid grid-cols-3 gap-1.5">
                {(
                  [
                    ["light", t("settings.light"), "bg-[#F5F4EF] text-[#15151A]"],
                    ["dark", t("settings.dark"), "bg-[#0E0E12] text-[#F2F1EC]"],
                    ["system", t("settings.system"), "bg-muted text-primary"],
                  ] as const
                ).map(([value, label, cls]) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={theme === value}
                    onClick={() => pickTheme(value)}
                    className={`h-16 rounded-2xl text-[13px] font-extrabold ${cls} ${
                      theme === value ? "ring-2 ring-brand ring-offset-2 ring-offset-surface" : "ring-1 ring-default"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            <div className="mt-2.5 rounded-2xl bg-surface py-1 shadow-card">
              {SECTIONS.map((sct, i) => (
                <button
                  key={sct.key}
                  onClick={() => setPhoneSection(sct.key)}
                  className={`flex min-h-14 w-full items-center gap-3 px-3.5 text-left ${i > 0 ? "border-t border-default" : ""}`}
                >
                  <span className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand-text">
                    <sct.icon size={16} aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[15px] font-extrabold text-primary">{sct.label}</span>
                    <span className="block text-xs font-semibold text-subtle">{SUBTITLES[sct.key]}</span>
                  </span>
                  <ChevronRight size={16} className="shrink-0 text-subtle" />
                </button>
              ))}
            </div>
            <button
              onClick={() => logout.mutate()}
              className="mt-3 h-[52px] w-full rounded-2xl bg-surface text-[15px] font-extrabold text-danger shadow-card"
            >
              {t("settings.logout")}
            </button>
          </div>
        ) : (
        <div className="flex min-h-0 flex-1 flex-col sm:flex-row">
          {/* Слева — переход по разделам (десктоп). На телефоне разделы —
              корневой экран выше, полоса не нужна. */}
          <nav className="hidden shrink-0 gap-1.5 overflow-x-auto px-3 pb-2 sm:flex sm:w-52 sm:flex-col sm:overflow-x-visible sm:px-3 sm:pb-3">
            {SECTIONS.map((s) => (
              <button
                key={s.key}
                onClick={() => setActive(s.key)}
                className={`flex h-10 shrink-0 items-center gap-2 whitespace-nowrap rounded-full px-3.5 text-left text-sm font-bold transition-colors sm:h-auto sm:rounded-xl sm:py-2 ${
                  active === s.key
                    ? "bg-accent text-on-accent sm:bg-brand-soft sm:text-brand-text"
                    : "bg-muted text-secondary hover:bg-muted-hover sm:bg-transparent"
                }`}
              >
                <s.icon size={15} className="shrink-0" aria-hidden />
                {s.label}
              </button>
            ))}
          </nav>

          {/* Скольжение при смене секции — то же, что у вкладок
              Активности. Направление по порядку в SECTIONS: вниз по
              списку приезжает справа, вверх — слева. key={active}
              обязателен, иначе React переиспользует узел и анимация не
              переигрывается. */}
          <div key={active} className={`min-w-0 flex-1 overflow-y-auto p-4 ${sectionSlide}`}>
          {active === "assistant" && (
            <>
          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-primary">Дополнительные инструкции</div>
            <div className="mb-2 text-xs text-subtle">
              Добавляются к базовым инструкциям ассистента, а не заменяют их — так безопасность и работа
              инструментов не ломаются, даже если тут написать что-то странное.
            </div>
            <textarea
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={4}
              placeholder="Например: обращайся на «ты», предпочитаю короткие ответы…"
              className="h-11 w-full rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
            />
            <button
              onClick={handleSave}
              disabled={updateInstructions.isPending}
              className="mt-2 flex items-center gap-2 h-10 rounded-xl bg-accent px-4 text-sm font-bold text-on-accent disabled:opacity-50"
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
            <div className="mb-1 text-sm font-medium text-primary">Умения ассистента</div>
            <div className="mb-2 text-xs text-subtle">Что ассистент умеет делать в этом диалоге.</div>
            {skillsLoading && <div className="text-sm text-subtle">Загрузка…</div>}
            <ul className="space-y-1">
              {toggleableSkills.map((skill) => (
                <li key={skill.name} className="flex items-center justify-between gap-2 rounded-xl border px-3 py-2">
                  <div className="min-w-0">
                    <div className="text-sm text-primary">{skill.label}</div>
                    <div className="truncate text-xs text-subtle">{skill.description}</div>
                  </div>
                  <button
                    role="switch"
                    aria-checked={skill.enabled}
                    onClick={() => toggleSkill(skill)}
                    disabled={updateDisabledTools.isPending}
                    className={`flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors disabled:opacity-50 ${
                      skill.enabled ? "justify-end bg-accent" : "justify-start bg-muted-active"
                    }`}
                  >
                    <span className="h-4 w-4 rounded-full bg-surface shadow" />
                  </button>
                </li>
              ))}
            </ul>
            {coreSkills.length > 0 && (
              <div className="mt-2 text-xs text-subtle">
                Всегда включено: {coreSkills.map((s) => s.label).join(", ")}.
              </div>
            )}
          </div>

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-primary">Модель ассистента</div>
            <div className="mb-2 text-xs text-subtle">
              Для сравнения провайдеров — переключение действует сразу, без перезагрузки, только для этого
              аккаунта.
            </div>
            <div className="flex gap-1.5">
              {LLM_PROVIDERS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => updateLlmProvider.mutate(p.value)}
                  disabled={updateLlmProvider.isPending}
                  className={`rounded border px-3 py-1.5 text-sm disabled:opacity-50 ${
                    (me?.llm_provider || "") === p.value
                      ? "border-strong bg-accent text-on-accent"
                      : "border-default text-secondary hover:bg-muted-hover"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-1 text-sm font-medium text-primary">Память ассистента</div>
            <div className="mb-2 text-xs text-subtle">
              Факты, которые ассистент помнит в каждом диалоге, не только когда сам что-то запомнил из
              разговора — например, что означают твои личные обозначения папок, город, состав семьи,
              устойчивые предпочтения. Чем больше здесь надёжных фактов, тем реже придётся объяснять
              одно и то же заново. Не стоит добавлять сюда точный домашний адрес и подобное — это
              заметки, а не факты для ассистента.
            </div>
            {isLoading && <div className="text-sm text-subtle">Загрузка…</div>}
            {!isLoading && (memories ?? []).length === 0 && (
              <div className="text-sm text-subtle">Пока ничего не запомнено</div>
            )}
            <ul className="space-y-1">
              {(memories ?? []).map((m) => (
                <li key={m.id} className="flex items-start justify-between gap-2 rounded-xl border px-3 py-2 text-sm">
                  <span className="flex-1">{m.content}</span>
                  <button
                    onClick={() => deleteMemory.mutate(m.id)}
                    title="Удалить"
                    className="flex h-6 w-6 shrink-0 items-center justify-center text-subtle hover:text-danger"
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              ))}
            </ul>
            <div className="mt-2 flex gap-2">
              <input
                value={newMemoryText}
                onChange={(e) => setNewMemoryText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleAddMemory();
                }}
                placeholder="Например: живу в Познани"
                className="min-w-0 flex-1 h-10 rounded-xl border bg-surface px-3 text-sm outline-none focus:ring-2 focus:ring-brand/40"
              />
              <button
                onClick={handleAddMemory}
                disabled={addMemory.isPending || !newMemoryText.trim()}
                className="flex shrink-0 items-center justify-center h-10 rounded-xl bg-accent px-4 text-sm font-bold text-on-accent disabled:opacity-50"
              >
                {addMemory.isPending ? <Spinner size={14} className="text-white" /> : <Plus size={14} />}
              </button>
            </div>
          </div>
            </>
          )}

          {active === "channels" && (
            <>
              <DigestSettings />

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-primary">Telegram</div>
            <div className="mb-2 text-xs text-subtle">
              Подключите бота — присылайте ему текст, фото, голосовые и видео, они автоматически станут заметками
              в отдельном личном спейсе «Telegram» (с авто-тегами и OCR, как и везде).
            </div>
            {telegramStatus?.linked ? (
              <div className="flex items-center justify-between gap-2 rounded-xl border px-3.5 py-2.5 text-sm">
                <span className="text-secondary">Подключено ✅</span>
                <button
                  onClick={() => telegramUnlink.mutate()}
                  disabled={telegramUnlink.isPending}
                  className="h-9 rounded-xl border border-default px-3 text-xs font-bold text-secondary hover:bg-muted-hover disabled:opacity-50"
                >
                  {telegramUnlink.isPending ? <Spinner size={12} /> : "Отключить"}
                </button>
              </div>
            ) : telegramDeepLink ? (
              <a
                href={telegramDeepLink}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 rounded bg-link px-3 py-1.5 text-sm text-white hover:bg-link/90"
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
                className="flex items-center gap-2 h-10 rounded-xl bg-accent px-4 text-sm font-bold text-on-accent disabled:opacity-50"
              >
                {telegramLinkCode.isPending && <Spinner size={14} className="text-white" />}
                Подключить
              </button>
            )}
            {telegramLinkCode.isError && (
              <div className="mt-1 text-xs text-danger">Telegram-бот пока не настроен на сервере.</div>
            )}
          </div>

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-primary">Почта</div>
            <div className="mb-2 text-xs text-subtle">
              Пересылайте важные письма на личный адрес — они появятся в отдельном спейсе «Почта» как заметки.
            </div>
            {mailStatus?.address ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2 h-10 rounded-xl border bg-surface px-3 text-sm outline-none focus:ring-2 focus:ring-brand/40">
                  <span className="truncate font-mono text-primary">{mailStatus.address}</span>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(mailStatus.address!).then(() => {
                        setMailCopied(true);
                        setTimeout(() => setMailCopied(false), 1500);
                      });
                    }}
                    title="Скопировать"
                    className="flex shrink-0 items-center gap-1 text-xs text-subtle hover:text-primary"
                  >
                    {mailCopied ? (
                      <>
                        <Check size={12} /> Скопировано
                      </>
                    ) : (
                      <>
                        <Copy size={12} /> Копировать
                      </>
                    )}
                  </button>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      if (window.confirm("Старый адрес перестанет принимать письма. Продолжить?")) {
                        regenerateMailAddress.mutate();
                      }
                    }}
                    disabled={regenerateMailAddress.isPending}
                    className="h-9 rounded-xl border border-default px-3 text-xs font-bold text-secondary hover:bg-muted-hover disabled:opacity-50"
                  >
                    {regenerateMailAddress.isPending ? <Spinner size={12} /> : "Пересоздать"}
                  </button>
                  <button
                    onClick={() => disableMailInbox.mutate()}
                    disabled={disableMailInbox.isPending}
                    className="h-9 rounded-xl border border-default px-3 text-xs font-bold text-secondary hover:bg-muted-hover disabled:opacity-50"
                  >
                    {disableMailInbox.isPending ? <Spinner size={12} /> : "Отключить"}
                  </button>
                </div>

                <div className="border-t pt-2">
                  <div className="mb-1 text-xs font-medium text-secondary">Свои адреса</div>
                  <div className="mb-2 text-xs text-subtle">
                    Письма, которые вы пересылаете себе или ставите этот адрес в копию, будут группироваться по
                    имени собеседника (отправителя пересланного письма или получателя), а не по вам самим.
                  </div>
                  {mailStatus.own_addresses.length > 0 && (
                    <div className="mb-2 space-y-1">
                      {mailStatus.own_addresses.map((addr) => (
                        <div key={addr} className="flex items-center justify-between gap-2 h-8 rounded-lg border bg-surface px-2.5 text-xs outline-none">
                          <span className="truncate font-mono text-secondary">{addr}</span>
                          <button
                            onClick={() => removeOwnMailAddress.mutate(addr)}
                            disabled={removeOwnMailAddress.isPending}
                            title="Убрать"
                            className="shrink-0 text-subtle hover:text-danger disabled:opacity-50"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <input
                      value={newOwnAddress}
                      onChange={(e) => setNewOwnAddress(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key !== "Enter" || !newOwnAddress.trim() || addOwnMailAddress.isPending) return;
                        addOwnMailAddress.mutate(newOwnAddress.trim(), { onSuccess: () => setNewOwnAddress("") });
                      }}
                      placeholder="your@email.com"
                      className="min-w-0 flex-1 h-8 rounded-lg border bg-surface px-2.5 text-xs outline-none"
                    />
                    <button
                      onClick={() => {
                        if (!newOwnAddress.trim() || addOwnMailAddress.isPending) return;
                        addOwnMailAddress.mutate(newOwnAddress.trim(), { onSuccess: () => setNewOwnAddress("") });
                      }}
                      disabled={addOwnMailAddress.isPending || !newOwnAddress.trim()}
                      className="shrink-0 h-8 rounded-lg border border-default px-2.5 text-xs font-bold text-secondary hover:bg-muted-hover disabled:opacity-50"
                    >
                      {addOwnMailAddress.isPending ? <Spinner size={12} /> : "Добавить"}
                    </button>
                  </div>
                  {addOwnMailAddress.isError && (
                    <div className="mt-1 text-xs text-danger">Некорректный email.</div>
                  )}
                </div>
              </div>
            ) : (
              <button
                onClick={() => generateMailAddress.mutate()}
                disabled={generateMailAddress.isPending}
                className="flex items-center gap-2 h-10 rounded-xl bg-accent px-4 text-sm font-bold text-on-accent disabled:opacity-50"
              >
                {generateMailAddress.isPending && <Spinner size={14} className="text-white" />}
                Создать адрес
              </button>
            )}
          </div>
            </>
          )}

          {active === "connect" && (
            <>
          <McpSettings />
            </>
          )}

          {active === "app" && (
            <>
          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-primary">Домашний часовой пояс</div>
            <div className="mb-2 text-xs text-subtle">
              Где вы обычно живёте — используется, чтобы верно понять время из писем и билетов (например
              "встреча в 17:30"), даже если вы сейчас в поездке. Для "напомни в 9 утра" в чате ассистент
              всегда ориентируется на часовой пояс браузера, эту настройку трогать не нужно.
            </div>
            <div className="flex items-center gap-2">
              <input
                value={timezoneInput}
                onChange={(e) => setTimezoneInput(e.target.value)}
                list="timezone-options"
                placeholder="Europe/Warsaw"
                className="h-11 w-full rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
              />
              <datalist id="timezone-options">
                {COMMON_TIMEZONES.map((tz) => (
                  <option key={tz} value={tz} />
                ))}
              </datalist>
              <button
                onClick={() => timezoneInput.trim() && updateTimezone.mutate(timezoneInput.trim())}
                disabled={updateTimezone.isPending || !timezoneInput.trim() || timezoneInput.trim() === me?.timezone}
                className="shrink-0 h-10 rounded-xl border border-default px-3.5 text-sm font-bold text-secondary hover:bg-muted-hover disabled:opacity-50"
              >
                Применить
              </button>
            </div>
            {updateTimezone.isError && (
              <div className="mt-1 text-xs text-danger">Не удалось сохранить — проверьте название пояса.</div>
            )}
          </div>

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-primary">Голос озвучивания</div>
            <div className="mb-2 text-xs text-subtle">
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
                      ? "border-strong bg-accent text-on-accent"
                      : "border-default text-secondary hover:bg-muted-hover"
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
                className="h-11 w-full rounded-xl border bg-surface px-3.5 text-sm outline-none focus:ring-2 focus:ring-brand/40"
              />
              <button
                onClick={() => customVoiceId.trim() && updateTtsVoice.mutate(customVoiceId.trim())}
                disabled={updateTtsVoice.isPending || !customVoiceId.trim()}
                className="shrink-0 h-10 rounded-xl border border-default px-3.5 text-sm font-bold text-secondary hover:bg-muted-hover disabled:opacity-50"
              >
                Применить
              </button>
            </div>
            {!isPresetVoice && (
              <div className="mt-1 text-xs text-subtle">Сейчас используется свой голос: {currentVoice}</div>
            )}
          </div>

          <div className="mb-6">
            <div className="flex items-center justify-between gap-2 rounded-xl border px-3 py-2">
              <div className="min-w-0">
                <div className="text-sm text-primary">Обработка загруженных файлов</div>
                <div className="text-xs text-subtle">
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
                  me?.auto_process_uploads ?? true ? "justify-end bg-accent" : "justify-start bg-muted-active"
                }`}
              >
                <span className="h-4 w-4 rounded-full bg-surface shadow" />
              </button>
            </div>
          </div>

          {isPushSupported() && (
            <div className="mb-6">
              <div className="flex items-center justify-between gap-2 rounded-xl border px-3 py-2">
                <div className="min-w-0">
                  <div className="text-sm text-primary">Уведомления в браузере</div>
                  <div className="text-xs text-subtle">
                    Напоминания придут даже если приложение закрыто. На iPhone работает только если приложение
                    установлено на экран (не просто открыто в Safari).
                  </div>
                </div>
                <button
                  role="switch"
                  aria-checked={pushSubscription.subscribed ?? false}
                  onClick={() => (pushSubscription.subscribed ? pushSubscription.unsubscribe() : pushSubscription.subscribe())}
                  disabled={pushSubscription.busy || pushSubscription.subscribed === null}
                  className={`flex h-5 w-9 shrink-0 items-center rounded-full px-0.5 transition-colors disabled:opacity-50 ${
                    pushSubscription.subscribed ? "justify-end bg-accent" : "justify-start bg-muted-active"
                  }`}
                >
                  <span className="h-4 w-4 rounded-full bg-surface shadow" />
                </button>
              </div>
            </div>
          )}

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-primary">Офлайн</div>
            <div className="mb-2 text-xs text-subtle">
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
                className="w-24 h-10 rounded-xl border bg-surface px-3 text-sm outline-none focus:ring-2 focus:ring-brand/40"
              />
              <span className="text-sm text-subtle">МБ</span>
              <button
                onClick={handleSaveMediaCacheLimit}
                className="h-10 rounded-xl border border-default px-3.5 text-sm font-bold text-secondary hover:bg-muted-hover"
              >
                {mediaCacheSaved ? "Сохранено" : "Сохранить"}
              </button>
            </div>
          </div>

          <div className="mb-6">
            <div className="mb-1 text-sm font-medium text-primary">Инвайт-коды</div>
            <div className="mb-2 text-xs text-subtle">
              Регистрация закрыта — новый человек может создать аккаунт только по коду. Создайте код и сообщите его
              лично тому, кого добавляете. Код одноразовый, действует 7 дней.
            </div>
            <button
              onClick={() => createInviteCode.mutate()}
              disabled={createInviteCode.isPending}
              className="flex items-center gap-2 h-10 rounded-xl bg-accent px-4 text-sm font-bold text-on-accent disabled:opacity-50"
            >
              {createInviteCode.isPending && <Spinner size={14} className="text-white" />}
              Создать код
            </button>
            {inviteCodes && inviteCodes.length > 0 && (
              <div className="mt-2 space-y-1">
                {inviteCodes.map((c) => {
                  const expired = !c.used_at && new Date(c.expires_at).getTime() < Date.now();
                  return (
                    <div key={c.id} className="flex items-center justify-between gap-2 h-10 rounded-xl border bg-surface px-3 text-sm outline-none focus:ring-2 focus:ring-brand/40">
                      <span className={`font-mono ${c.used_at || expired ? "text-subtle line-through" : "text-primary"}`}>
                        {c.code}
                      </span>
                      {c.used_at ? (
                        <span className="text-xs text-subtle">использован</span>
                      ) : expired ? (
                        <span className="text-xs text-subtle">истёк</span>
                      ) : (
                        <button
                          onClick={() => {
                            navigator.clipboard.writeText(c.code).then(() => {
                              setCopiedCodeId(c.id);
                              setTimeout(() => setCopiedCodeId((v) => (v === c.id ? null : v)), 1500);
                            });
                          }}
                          title="Скопировать"
                          className="flex items-center gap-1 text-xs text-subtle hover:text-primary"
                        >
                          {copiedCodeId === c.id ? (
                            <>
                              <Check size={12} /> Скопировано
                            </>
                          ) : (
                            <>
                              <Copy size={12} /> Копировать
                            </>
                          )}
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
            </>
          )}
          </div>
        </div>
        )}
      </div>
    </div>
  );
}

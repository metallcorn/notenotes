// Известные видео-платформы, которые можно встроить плеером прямо в
// заметке вместо обычной карточки-превью (Slack-style unfurl,
// LinkPreviewCard.tsx) — реальная просьба пользователя после вставки
// ссылки на YouTube. Список намеренно узкий и явный (не общий
// эвристический детектор "это видео?"), чтобы iframe встраивался только с
// заведомо безопасных доменов, а не с произвольного стороннего сайта.
export interface EmbedInfo {
  platform: "youtube" | "vimeo";
  embedUrl: string;
}

function youtubeId(url: URL): string | null {
  if (url.hostname === "youtu.be") {
    return url.pathname.slice(1) || null;
  }
  const host = url.hostname.replace(/^(www|m)\./, "");
  if (host !== "youtube.com" && host !== "youtube-nocookie.com") return null;
  if (url.pathname === "/watch") return url.searchParams.get("v");
  const shorts = url.pathname.match(/^\/shorts\/([^/]+)/);
  if (shorts) return shorts[1];
  const embed = url.pathname.match(/^\/embed\/([^/]+)/);
  if (embed) return embed[1];
  return null;
}

function vimeoId(url: URL): string | null {
  if (url.hostname.replace(/^www\./, "") !== "vimeo.com") return null;
  const match = url.pathname.match(/^\/(\d+)/);
  return match ? match[1] : null;
}

export function detectEmbed(rawUrl: string): EmbedInfo | null {
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;

  const yt = youtubeId(url);
  // youtube-nocookie.com — без cookies до первого клика play, тот же
  // приём, что рекомендует сам YouTube для embed на сторонних сайтах.
  if (yt) return { platform: "youtube", embedUrl: `https://www.youtube-nocookie.com/embed/${yt}` };

  const vimeo = vimeoId(url);
  if (vimeo) return { platform: "vimeo", embedUrl: `https://player.vimeo.com/video/${vimeo}` };

  return null;
}

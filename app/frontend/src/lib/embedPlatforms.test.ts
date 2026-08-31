import { describe, expect, it } from "vitest";
import { detectEmbed } from "./embedPlatforms";

describe("detectEmbed", () => {
  it("youtube.com/watch?v=", () => {
    expect(detectEmbed("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s")).toEqual({
      platform: "youtube",
      embedUrl: "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    });
  });

  it("youtu.be короткая ссылка", () => {
    expect(detectEmbed("https://youtu.be/dQw4w9WgXcQ")).toEqual({
      platform: "youtube",
      embedUrl: "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
    });
  });

  it("youtube.com/shorts/", () => {
    expect(detectEmbed("https://www.youtube.com/shorts/abc123XYZ_-")?.embedUrl).toBe(
      "https://www.youtube-nocookie.com/embed/abc123XYZ_-",
    );
  });

  it("vimeo.com/<id>", () => {
    expect(detectEmbed("https://vimeo.com/76979871")).toEqual({
      platform: "vimeo",
      embedUrl: "https://player.vimeo.com/video/76979871",
    });
  });

  it("обычный сайт — не встраивается", () => {
    expect(detectEmbed("https://example.com/article")).toBeNull();
  });

  it("youtube.com без video id (главная страница) — не встраивается", () => {
    expect(detectEmbed("https://www.youtube.com/")).toBeNull();
  });

  it("некорректный URL — не бросает исключение", () => {
    expect(detectEmbed("не url")).toBeNull();
  });
});

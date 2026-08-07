// Строим .ics (RFC 5545) на клиенте из данных, которые вернул тул
// create_calendar_event — бэкенд ничего не хранит, файл собирается на лету
// в момент клика. Время без указания зоны (floating) — ни бэкенд, ни модель
// не знают часовой пояс события надёжнее, чем открывающий файл человек.

export interface CalendarEventData {
  title: string;
  start: string;
  end: string;
  all_day: boolean;
  location?: string;
  description?: string;
}

function escapeIcsText(text: string): string {
  return text.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\n/g, "\\n");
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function toIcsDate(iso: string, allDay: boolean): string {
  if (allDay) return iso.replace(/-/g, "");
  const d = new Date(iso);
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}T${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

export function buildIcs(event: CalendarEventData): string {
  const uid = `${Date.now()}-${Math.random().toString(36).slice(2)}@notenotes`;
  const now = new Date();
  const dtStamp = `${now.getUTCFullYear()}${pad(now.getUTCMonth() + 1)}${pad(now.getUTCDate())}T${pad(now.getUTCHours())}${pad(now.getUTCMinutes())}${pad(now.getUTCSeconds())}Z`;

  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Notenotes//RU",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${uid}`,
    `DTSTAMP:${dtStamp}`,
    event.all_day ? `DTSTART;VALUE=DATE:${toIcsDate(event.start, true)}` : `DTSTART:${toIcsDate(event.start, false)}`,
    event.all_day ? `DTEND;VALUE=DATE:${toIcsDate(event.end, true)}` : `DTEND:${toIcsDate(event.end, false)}`,
    `SUMMARY:${escapeIcsText(event.title)}`,
  ];
  if (event.location) lines.push(`LOCATION:${escapeIcsText(event.location)}`);
  if (event.description) lines.push(`DESCRIPTION:${escapeIcsText(event.description)}`);
  lines.push("END:VEVENT", "END:VCALENDAR");
  return lines.join("\r\n");
}

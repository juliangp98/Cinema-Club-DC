// Every date and time the site shows, formatted one way (R9b). Each takes a
// Date or an ISO string. US English, the visitor's own time zone.
const fmt = opts => {
  const f = new Intl.DateTimeFormat("en-US", opts);
  return v => f.format(v instanceof Date ? v : new Date(v));
};

export const time = fmt({ hour: "numeric", minute: "2-digit" });                        // 7:30 PM
export const shortTime = v => time(v).replace(":00 ", " ");                               // 7 PM
export const weekday = fmt({ weekday: "short" });                                         // Tue
export const monthDay = fmt({ month: "short", day: "numeric" });                          // Oct 14
export const dayDate = fmt({ weekday: "short", month: "short", day: "numeric" });         // Tue, Oct 14
export const longDayDate = fmt({ weekday: "long", month: "short", day: "numeric" });      // Tuesday, Oct 14
export const numericDay = fmt({ weekday: "short", month: "numeric", day: "numeric" });    // Tue, 10/14
export const fullDate = fmt({ month: "short", day: "numeric", year: "numeric" });         // Oct 14, 2026
export const monthYear = fmt({ month: "long", year: "numeric" });                         // October 2026
export const dayDateTime = v => `${dayDate(v)} · ${time(v)}`;                             // Tue, Oct 14 · 7:30 PM
export const dayDateAt = fmt({ weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
export const dayShortTime = v => `${weekday(v)} ${shortTime(v)}`;                         // Tue 7 PM

// Has a screening started? Its start is the theatre's clock; `starts_at`
// carries that city's offset, so this is right wherever the viewer is.
export const hasStarted = s => new Date(s.starts_at || s.start_time) <= new Date();

// "just now", "5m ago", "3h ago", "2d ago", then the date.
export function ago(v) {
  const s = Math.max(0, Math.floor((Date.now() - new Date(v)) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 7 * 86400) return `${Math.floor(s / 86400)}d ago`;
  return monthDay(v);
}

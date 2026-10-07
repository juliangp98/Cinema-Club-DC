import Menu, { MenuItem } from "./Menu";
import { CalendarIcon } from "./icons";
import { TicketDiscord } from "./DiscordShare";

const RSVP = [
  { status: "going", label: "Going" },
  { status: "maybe", label: "Maybe" },
  { status: "not_going", label: "Can't go" },
];
const ATTENDED = [
  { status: "went", label: "Went" },
  { status: "missed", label: "Didn't go" },
];

const day = d => d.toLocaleDateString("en-US", { weekday: "short" });
const date = d => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
const time = d => d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

// A choice of one: pick again to clear (e.g. un-RSVP).
export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(o => (
        <button
          key={o.status}
          type="button"
          className={`seg-btn seg-${o.status}${value === o.status ? " on" : ""}`}
          aria-pressed={value === o.status}
          onClick={() => onChange(value === o.status ? null : o.status)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// One screening as a ticket stub: when on the stub; where, format and
// billing in the body; RSVP (or, once it has started, Went / Didn't go),
// tickets and add-to-calendar as actions; then what to share in Discord.
export default function TicketRow({ showtime: s, apiBase, groupId, onRsvp, onAttendance, showTheatre = true }) {
  const start = new Date(s.start_time);
  const started = start <= new Date();
  const theatre = s.theatre?.name;

  async function googleCalendar() {
    try {
      const r = await fetch(`${apiBase}/api/showtimes/${s.id}/gcal-url`, { credentials: "include" });
      if (r.ok) window.open((await r.json()).url, "_blank", "noopener");
    } catch { /* ignore */ }
  }

  return (
    <div className={`ticket${s.is_sold_out && !started ? " sold-out" : ""}`}>
      <div className="ticket-stub" aria-hidden="true">
        <span className="ticket-day">{day(start)}</span>
        <span className="ticket-date">{date(start)}</span>
      </div>
      <div className="ticket-body">
        <div className="ticket-head">
          <span className="ticket-time">{time(start)}</span>
          {s.end_time && <span className="ticket-end">– {time(new Date(s.end_time))}</span>}
          {s.format_label && <span className="chip gold">{s.format_label}</span>}
          {s.is_sold_out && !started && <span className="chip ticket-soldout">Sold out</span>}
        </div>
        {showTheatre && theatre && <div className="ticket-where">{theatre}</div>}
        {s.event_label && <div className="ticket-billing">{s.event_label}</div>}

        <div className="ticket-actions">
          {started ? (
            <Segmented label="Did you go?" options={ATTENDED} value={s.user_attendance}
                       onChange={v => onAttendance?.(s.id, v)} />
          ) : (
            <Segmented label="Your RSVP" options={RSVP} value={s.user_rsvp} onChange={v => onRsvp?.(s.id, v)} />
          )}
          {!started && (
            <div className="ticket-links">
              {s.purchase_link && !s.is_sold_out && (
                <a className="btn btn-sm btn-primary" href={s.purchase_link} target="_blank" rel="noopener noreferrer">
                  Tickets ↗
                </a>
              )}
              <Menu label="Add to calendar" triggerClassName="btn btn-sm" trigger={<><CalendarIcon /> Add</>}>
                <MenuItem onSelect={googleCalendar}>Google Calendar</MenuItem>
                <MenuItem onSelect={() => { window.location.href = `${apiBase}/api/showtimes/${s.id}/ical`; }}>
                  Apple / Outlook (.ics)
                </MenuItem>
              </Menu>
            </div>
          )}
        </div>
        {!started && <TicketDiscord showtime={s} apiBase={apiBase} groupId={groupId} />}
        {started && s.user_attendance === "went" && (
          <div className="ticket-note">Logged to your watch history — share your take in the discussion.</div>
        )}
      </div>
    </div>
  );
}

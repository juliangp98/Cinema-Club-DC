import { Link } from "react-router-dom";
import Poster from "./Poster";
import { Segmented } from "./TicketRow";
import { dayDate } from "../dates";

// Tickets (R15): one choice for the Calendar, Browse and theatre pages, kept
// in the address as ?tickets= (the server filters the same way, discover.TICKETS).
// All also shows films a theatre has announced (tickets not on sale yet) on
// the day it expects them; Coming soon shows only those.
export const TICKET_OPTIONS = [
  { status: "all", label: "All" },
  { status: "available", label: "Available" },
  { status: "soldout", label: "Sold out" },
  { status: "soon", label: "Coming soon" },
];

export default function TicketChips({ value, onChange }) {
  return <Segmented label="Tickets" options={TICKET_OPTIONS} value={value || "all"}
                    onChange={v => onChange(!v || v === "all" ? null : v)} />;
}

// An announced film as a poster card: where, the day it's expected, tickets soon.
export function AnnouncedCard({ a }) {
  return (
    <Link to={`/films/${a.movie.id}`} className="poster-card announced-card">
      <div className="poster-card-img">
        <Poster movie={a.movie} fill />
        <span className="ui-badge gold poster-card-badge">Tickets soon</span>
      </div>
      <span className="poster-card-title">{a.movie.title}</span>
      <span className="announced-when">
        <span className="theatre-link-dot" style={{ "--tcolor": a.theatre.color }} aria-hidden="true" />
        {a.theatre.short_name || a.theatre.name} · {dayDate(`${a.date}T12:00:00`)}
      </span>
    </Link>
  );
}

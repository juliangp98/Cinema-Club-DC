import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { fullDate, dayDateTime } from "../dates";
import { attend, getJson } from "../api";
import { TasteMatch } from "../ui/TasteChips";

// A member's lists (R15: shared by their page, /people/<id>, and your own Me
// page): watchlist, going, watch history, and — on someone else's — Compare.
// `onOpen(showtimeId)` opens a screening in place.

const formatDate = fullDate, formatWhen = dayDateTime;

function useList(url) {
  const [data, setData] = useState(null);
  useEffect(() => {
    setData(null);
    getJson(url).then(setData).catch(() => setData({ error: true }));
  }, [url]);
  return [data, setData];
}

const STATUS_LABEL = { going: "Going", maybe: "Maybe", went: "Saw it" };
const BADGE_TONE = { going: "go", maybe: "gold", went: "strong" };

// One screening in a list: title, when + where, and an optional status chip.
// Clickable rows open the screening's drawer.
function ScreeningRow({ item, status, onOpen }) {
  const body = (
    <>
      <span className="list-row-text">
        <span className="list-row-title">{item.title}</span>
        <span className="list-row-meta">
          {formatWhen(item.start_time)} · {item.theatre}{item.format_label ? ` · ${item.format_label}` : ""}
        </span>
      </span>
      {status && <span className={`ui-badge ${BADGE_TONE[status] || ""}`}>{STATUS_LABEL[status] || status}</span>}
    </>
  );
  return (
    <li>
      <button type="button" className="list-row" onClick={() => onOpen(item.showtime_id)}>{body}</button>
    </li>
  );
}

// A watchlisted film: opens its film page (every showing, details). 📓 = it
// came from their Letterboxd watchlist.
function FilmRow({ movie, next, source }) {
  const navigate = useNavigate();
  const text = (
    <span className="list-row-text">
      <span className="list-row-title">
        {movie.title}{movie.release_year ? ` (${movie.release_year})` : ""}
        {source === "letterboxd" && <span className="chip list-row-chip" title="From their Letterboxd watchlist">📓 Letterboxd</span>}
      </span>
      <span className="list-row-meta">
        {next ? `Next: ${formatWhen(next.start_time)} · ${next.theatre}` : "No showings scheduled"}
      </span>
    </span>
  );
  return (
    <li>
      <button type="button" className={`list-row${next ? "" : " muted"}`} onClick={() => navigate(`/films/${movie.id}`)}>
        {text}
      </button>
    </li>
  );
}

function ListState({ data, empty }) {
  if (!data) return <div className="list-empty">Loading…</div>;
  if (data.error) return <div className="list-empty">Couldn't load this right now.</div>;
  return <div className="list-empty">{empty}</div>;
}

export function WatchlistTab({ userId, apiBase, onOpen }) {
  const [data] = useList(`${apiBase}/api/users/${userId}/watchlist`);
  if (!data || data.error || !data.items.length) {
    return <ListState data={data} empty="No films on the watchlist yet." />;
  }
  return (
    <ul className="list-rows">
      {data.items.map(i => <FilmRow key={i.movie.id} movie={i.movie} next={i.next} source={i.source} />)}
    </ul>
  );
}

export function GoingTab({ userId, apiBase, onOpen }) {
  const [data] = useList(`${apiBase}/api/users/${userId}/rsvps`);
  if (!data || data.error || !data.items.length) {
    return <ListState data={data} empty="No upcoming RSVPs." />;
  }
  return (
    <ul className="list-rows">
      {data.items.map(i => <ScreeningRow key={i.showtime_id} item={i} status={i.status} onOpen={onOpen} />)}
    </ul>
  );
}

// Watch history: screenings this member saw (confirmed "went", or RSVP'd going
// and never said otherwise). On your own profile every entry is editable, and
// ones you marked "didn't go" stay listed so you can correct them.
export function HistoryTab({ userId, apiBase, onOpen, onChange }) {
  const [data, setData] = useList(`${apiBase}/api/users/${userId}/history`);

  async function setStatus(item, status) {
    if (!(await attend(apiBase, item.showtime_id, status).catch(() => null))) return;
    onChange?.();
    setData(d => ({
      ...d,
      // Clearing a "didn't go" puts it back to an unconfirmed RSVP.
      items: d.items.map(i => (i.showtime_id === item.showtime_id ? { ...i, status: status || "going" } : i)),
    }));
  }

  if (!data || data.error || !data.items.length) {
    return <ListState data={data} empty="Nothing logged yet." />;
  }
  const seen = data.items.filter(i => i.status !== "missed").length;
  return (
    <>
      <div className="list-count">{seen} screening{seen === 1 ? "" : "s"} seen</div>
      <ul className="history-list">
        {data.items.map(i => (
          <li key={i.showtime_id} className={`history-item${i.status === "missed" ? " missed" : ""}`}>
            <button type="button" className="history-text" onClick={() => onOpen(i.showtime_id)}>
              <span className="history-title">{i.title}</span>
              <span className="history-meta">
                {formatDate(i.start_time)} · {i.theatre}{i.format_label ? ` · ${i.format_label}` : ""}
              </span>
            </button>
            {data.own ? (
              <div className="history-actions">
                {[["went", "Went"], ["missed", "Didn't go"]].map(([status, label]) => (
                  <button
                    key={status}
                    className={`btn btn-sm att-opt-${status}${i.status === status ? " selected" : ""}`}
                    onClick={() => setStatus(i, i.status === status ? null : status)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            ) : (
              <span className="history-mark" title={i.status === "went" ? "Confirmed" : "RSVP'd going"}>
                {i.status === "went" ? "✓" : "🎟"}
              </span>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

// Where you and this member line up — for planning outings together.
export function CompareTab({ userId, apiBase, onOpen }) {
  const [data] = useList(`${apiBase}/api/users/${userId}/compare`);
  if (!data || data.error) return <ListState data={data} />;
  const name = data.name;
  const sections = [
    ["You both want to see", data.both_want.map(i => (
      <FilmRow key={`w${i.movie.id}`} movie={i.movie} next={i.next} />))],
    ["You're both going", data.both_going.map(i => (
      <ScreeningRow key={`b${i.showtime_id}`} item={i} status={i.status} onOpen={onOpen} />))],
    [`${name}'s going to something on your watchlist`, data.they_go_you_want.map(i => (
      <ScreeningRow key={`t${i.showtime_id}`} item={i} status={i.status} onOpen={onOpen} />))],
    [`You're going to something on ${name}'s watchlist`, data.you_go_they_want.map(i => (
      <ScreeningRow key={`y${i.showtime_id}`} item={i} status={i.status} onOpen={onOpen} />))],
    ["Seen together", data.seen_together.map(i => (
      <ScreeningRow key={`s${i.showtime_id}`} item={i} onOpen={onOpen} />))],
  ].filter(([, rows]) => rows.length);
  const match = data.taste?.score != null && <TasteMatch match={data.taste} />;
  if (!sections.length) {
    return <>{match}<div className="list-empty">Nothing lines up yet — add films to your watchlist or RSVP to a screening.</div></>;
  }
  return <>{match}{sections.map(([title, rows]) => (
    <div key={title} className="compare-section">
      <div className="compare-section-title">{title} <span className="compare-count">{rows.length}</span></div>
      <ul className="list-rows">{rows}</ul>
    </div>
  ))}</>;
}

// The tab bar over a member's lists — yours on Me (Watchlist, Going,
// History), someone's on their page (Compare first). `refreshKey` reloads the
// lists (after an RSVP or check-in elsewhere on the page).
export default function ProfileLists({ userId, apiBase, own, onOpen, onChange, refreshKey = 0 }) {
  const tabs = own ? ["Watchlist", "Going", "History"] : ["Compare", "Watchlist", "Going", "History"];
  const [tab, setTab] = useState(tabs[0]);
  useEffect(() => setTab(own ? "Watchlist" : "Compare"), [userId, own]);
  return (
    <>
      <div className="profile-tabs" role="tablist">
        {tabs.map(t => (
          <button key={t} type="button" role="tab" aria-selected={tab === t}
                  className={`profile-tab${tab === t ? " active" : ""}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div className="profile-tab-panel" role="tabpanel" key={`${tab}-${refreshKey}`}>
        {tab === "Compare" && <CompareTab userId={userId} apiBase={apiBase} onOpen={onOpen} />}
        {tab === "Watchlist" && <WatchlistTab userId={userId} apiBase={apiBase} onOpen={onOpen} />}
        {tab === "Going" && <GoingTab userId={userId} apiBase={apiBase} onOpen={onOpen} />}
        {tab === "History" && <HistoryTab userId={userId} apiBase={apiBase} onOpen={onOpen} onChange={onChange} />}
      </div>
    </>
  );
}

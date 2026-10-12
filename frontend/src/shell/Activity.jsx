import { useState, useEffect, useCallback } from "react";
import { Link } from "react-router-dom";
import Sheet from "../ui/Sheet";
import Tabs from "../ui/Tabs";
import Poster from "../ui/Poster";
import Feed from "../pages/Feed";
import NotifySettings from "../components/NotifySettings";
import { BellIcon } from "../ui/icons";
import { ago } from "../dates";

// The bell in the top bar, on every page: "For you" — your alerts (R8: a film
// on your watchlist got showings…; read/unread is kept on the server) — and
// "Club" — what the club did since you last looked (remembered per group in
// this browser). The count adds both up.

const seenKey = g => `cinemaclub_activity_seen_${g}`;
function readSeen(g) { try { return localStorage.getItem(seenKey(g)); } catch { return null; } }
function writeSeen(g, iso) { try { localStorage.setItem(seenKey(g), iso); } catch { /* private mode */ } }

// Your own RSVPs, watchlist adds and polls aren't news to you.
function fromOthers(card, user) {
  switch (card.type) {
    case "screening": return card.activity?.[0]?.user?.id !== user.id;
    case "watchlist":
    case "joined": return card.users.some(u => u.id !== user.id);
    case "poll": return card.poll.creator !== user.name;
    default: return true;
  }
}

const CHECK_EVERY_MS = 2 * 60 * 1000;

export function useActivity({ apiBase, groupId, user }) {
  const [clubUnread, setClubUnread] = useState(0);
  const [mineUnread, setMineUnread] = useState(0);
  const [tab, setTab] = useState(null);        // the open panel's tab; null = closed

  const check = useCallback(async () => {
    if (!user) return;
    fetch(`${apiBase}/api/notifications?count=1`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : null)).then(d => d && setMineUnread(d.unread)).catch(() => {});
    if (!groupId) { setClubUnread(0); return; }
    const r = await fetch(`${apiBase}/api/feed?group_id=${groupId}`, { credentials: "include" }).catch(() => null);
    if (!r?.ok) return;
    const { cards } = await r.json();
    let seen = readSeen(groupId);
    if (!seen) {                     // first visit: start counting from now
      seen = new Date().toISOString();
      writeSeen(groupId, seen);
    }
    const since = new Date(seen);
    setClubUnread(cards.filter(c => new Date(c.at) > since && fromOthers(c, user)).length);
  }, [apiBase, groupId, user]);

  useEffect(() => {
    check();
    const timer = setInterval(() => { if (!document.hidden) check(); }, CHECK_EVERY_MS);
    const onVisible = () => { if (!document.hidden) check(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [check]);

  // Opens on your alerts when there are new ones (or there's no club), else the club.
  const open = useCallback(which => {
    setTab(which || (mineUnread > 0 || !groupId ? "mine" : "club"));
  }, [mineUnread, groupId]);
  const seeClub = useCallback(() => {
    if (groupId) writeSeen(groupId, new Date().toISOString());
    setClubUnread(0);
  }, [groupId]);
  const close = useCallback(() => {
    if (tab === "club") seeClub();
    setTab(null);
  }, [tab, seeClub]);

  return { unread: clubUnread + mineUnread, isOpen: tab !== null, tab, setTab, open, close,
           seeClub, seeMine: () => setMineUnread(0) };
}

export function ActivityBell({ unread, onOpen }) {
  const label = unread ? `Notifications, ${unread} new` : "Notifications";
  return (
    <button type="button" className="topbar-bell" onClick={() => onOpen()} aria-label={label} title="Notifications">
      <BellIcon />
      {unread > 0 && <span className="topbar-bell-count" aria-hidden="true">{unread > 9 ? "9+" : unread}</span>}
    </button>
  );
}


// Your alerts, newest first; opening them marks them read.
function ForYou({ apiBase, onSeen, onClose }) {
  const [items, setItems] = useState(null);
  const [settings, setSettings] = useState(false);
  useEffect(() => {
    fetch(`${apiBase}/api/notifications`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : { items: [] }))
      .then(d => {
        setItems(d.items);
        if (d.unread) {
          fetch(`${apiBase}/api/notifications/read`, { method: "POST", credentials: "include",
            headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
          onSeen();
        }
      })
      .catch(() => setItems([]));
  }, [apiBase]);   // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="alerts">
      <div className="alerts-bar">
        <button type="button" className="btn btn-sm btn-ghost" aria-expanded={settings} onClick={() => setSettings(v => !v)}>
          {settings ? "Done" : "Notification settings"}
        </button>
      </div>
      {settings && <NotifySettings apiBase={apiBase} />}
      {items === null ? null : !items.length ? (
        <p className="feed-empty">
          No alerts yet. Add films to your watchlist — even ones that aren't playing — and you'll hear here
          (and by Discord or email, as you choose) when a theatre books them.
        </p>
      ) : (
        <ul className="alerts-list">
          {items.map(n => (
            <li key={n.id} className={`alert${n.read ? "" : " unread"}`}>
              <Link to={n.link} onClick={onClose} className="alert-link">
                <Poster movie={{ title: n.title || n.headline, poster_url: n.poster_url }} className="alert-poster" />
                <span className="alert-text">
                  <span className="alert-headline">{n.headline}</span>
                  {n.detail && <span className="alert-detail">{n.detail}</span>}
                  <span className="alert-when">{ago(n.created_at)}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ActivityPanel({ user, apiBase, groupId, activity }) {
  const tabs = [{ key: "mine", label: "For you" }, ...(groupId ? [{ key: "club", label: "Club" }] : [])];
  const pick = key => {
    if (activity.tab === "club" && key !== "club") activity.seeClub();
    activity.setTab(key);
  };
  return (
    <Sheet label="Notifications" className="activity-sheet" onClose={activity.close}>
      <div className="activity-panel">
        <h2 className="ui-section-title activity-title"><span className="deco">Notifications</span></h2>
        {tabs.length > 1 && <div className="activity-tabs"><Tabs tabs={tabs} value={activity.tab} onChange={pick} label="Notifications" /></div>}
        {activity.tab === "club" && groupId
          ? <Feed user={user} apiBase={apiBase} groupId={groupId} />
          : <ForYou apiBase={apiBase} onSeen={activity.seeMine} onClose={activity.close} />}
      </div>
    </Sheet>
  );
}

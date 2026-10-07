import { useState, useEffect, useCallback } from "react";
import Sheet from "../ui/Sheet";
import Feed from "../pages/Feed";
import { BellIcon } from "../ui/icons";

// The club's activity, from any page: a bell in the top bar (with how many
// new things others did since you last looked) opens the feed in a panel.
// "Last looked" is remembered per group in this browser.

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
  const [unread, setUnread] = useState(0);
  const [isOpen, setOpen] = useState(false);

  const check = useCallback(async () => {
    if (!groupId) return;
    const r = await fetch(`${apiBase}/api/feed?group_id=${groupId}`, { credentials: "include" }).catch(() => null);
    if (!r?.ok) return;
    const { cards } = await r.json();
    let seen = readSeen(groupId);
    if (!seen) {                     // first visit: start counting from now
      seen = new Date().toISOString();
      writeSeen(groupId, seen);
    }
    const since = new Date(seen);
    setUnread(cards.filter(c => new Date(c.at) > since && fromOthers(c, user)).length);
  }, [apiBase, groupId, user]);

  useEffect(() => {
    check();
    const timer = setInterval(() => { if (!document.hidden) check(); }, CHECK_EVERY_MS);
    const onVisible = () => { if (!document.hidden) check(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [check]);

  const open = useCallback(() => {
    writeSeen(groupId, new Date().toISOString());
    setUnread(0);
    setOpen(true);
  }, [groupId]);
  const close = useCallback(() => {
    writeSeen(groupId, new Date().toISOString());
    setOpen(false);
  }, [groupId]);

  return { unread, isOpen, open, close };
}

export function ActivityBell({ unread, onOpen }) {
  const label = unread ? `Club activity, ${unread} new` : "Club activity";
  return (
    <button type="button" className="topbar-bell" onClick={onOpen} aria-label={label} title="Club activity">
      <BellIcon />
      {unread > 0 && <span className="topbar-bell-count" aria-hidden="true">{unread > 9 ? "9+" : unread}</span>}
    </button>
  );
}

export function ActivityPanel({ user, apiBase, groupId, onClose }) {
  return (
    <Sheet label="Club activity" className="activity-sheet" onClose={onClose}>
      <div className="activity-panel">
        <h2 className="ui-section-title activity-title"><span className="deco">Club activity</span></h2>
        {groupId
          ? <Feed user={user} apiBase={apiBase} groupId={groupId} />
          : <p className="feed-empty">Join a group to see what the club is up to.</p>}
      </div>
    </Sheet>
  );
}

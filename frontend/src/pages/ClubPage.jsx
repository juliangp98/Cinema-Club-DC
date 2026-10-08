import { useState, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { SectionTitle } from "../ui/PageHeader";
import Tabs from "../ui/Tabs";
import Avatar, { ClubBadge } from "../ui/Avatar";
import UserProfileDrawer from "../components/UserProfileDrawer";
import ClubSettings from "../components/ClubSettings";
import CalendarLinks from "../components/CalendarLinks";
import Feed from "./Feed";
import { ClubWeek } from "./DiscoverPage";
import { useShell } from "../shell/AppShell";
import useShowtimeSheet from "../shell/useShowtimeSheet";
import { roleLabel } from "../roles";
import "./Club.css";

const MEDALS = ["🥇", "🥈", "🥉"];
const ROLE_ORDER = { admin: 0, organizer: 1, member: 2, viewer: 3 };

// The club's page (R6b): who it is, this week and recent activity, members,
// the leaderboard, and (for admins) its settings. ?tab= picks the tab, so the
// old /members and /leaderboard links land on theirs.
export default function ClubPage({ user, apiBase }) {
  const shell = useShell();
  const navigate = useNavigate();
  const group = shell?.group;
  const [params, setParams] = useSearchParams();
  const [profileUserId, setProfileUserId] = useState(null);
  const [theatreNames, setTheatreNames] = useState({});
  const isAdmin = shell?.role === "admin";
  const tabs = [{ key: "overview", label: "Overview" }, { key: "members", label: "Members" },
                { key: "leaderboard", label: "Leaderboard" }, ...(isAdmin ? [{ key: "settings", label: "Settings" }] : [])];
  const tab = tabs.some(t => t.key === params.get("tab")) ? params.get("tab") : "overview";
  const setTab = key => setParams(key === "overview" ? {} : { tab: key }, { replace: true });
  const { openShowtime, sheet } = useShowtimeSheet({ user, apiBase, groupId: group?.id, onViewProfile: setProfileUserId });

  useEffect(() => {
    fetch(`${apiBase}/api/theatres`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : []))
      .then(ts => setTheatreNames(Object.fromEntries(ts.map(t => [t.slug, t.short_name || t.name]))))
      .catch(() => {});
  }, [apiBase]);

  if (!group) {
    return (
      <div className="page narrow">
        <p className="pv-empty">You're not in a club yet. <Link to="/groups">Find or start one →</Link></p>
      </div>
    );
  }

  const theatres = (group.theatres || []).map(s => theatreNames[s] || s);
  return (
    <div className="page club-page">
      <header className="club-hero">
        <ClubBadge group={group} size={84} />
        <div className="club-hero-text">
          <h1 className="deco club-hero-name">{group.name}</h1>
          {group.description && <p className="club-hero-desc">{group.description}</p>}
          <p className="club-hero-meta">
            {group.member_count} member{group.member_count === 1 ? "" : "s"} · you're {isAdmin ? "an" : "a"} {roleLabel(shell.role).toLowerCase()}
            {group.discord && " · has a Discord server"}
          </p>
          {theatres.length > 0 && <p className="club-hero-theatres">{theatres.join(" · ")}</p>}
        </div>
      </header>

      <Tabs tabs={tabs} value={tab} onChange={setTab} label="Club" />
      <div role="tabpanel" className="club-panel">
        {tab === "overview" && (
          <>
            <ClubWeek apiBase={apiBase} groupId={group.id} viewerId={user.id} onOpenShowtime={openShowtime}
                      onOpenActivity={shell.openActivity} />
            <SectionTitle>In your calendar</SectionTitle>
            <CalendarLinks apiBase={apiBase} clubId={group.id} />
            <SectionTitle>Recent activity</SectionTitle>
            <div className="club-feed"><Feed user={user} apiBase={apiBase} groupId={group.id} /></div>
          </>
        )}
        {tab === "members" && <Members group={group} apiBase={apiBase} viewerId={user.id} onOpen={setProfileUserId} />}
        {tab === "leaderboard" && <Leaderboard group={group} apiBase={apiBase} viewerId={user.id} onOpen={setProfileUserId} />}
        {tab === "settings" && isAdmin && (
          <ClubSettings group={group} apiBase={apiBase} viewerId={user.id} onViewProfile={setProfileUserId}
                        onChanged={() => shell.refreshGroups?.()}
                        onDeleted={async () => { await shell.refreshGroups?.(); navigate("/groups"); }} />
        )}
      </div>

      {sheet}
      {profileUserId && (
        <UserProfileDrawer userId={profileUserId} viewerId={user.id} apiBase={apiBase}
                           onClose={() => setProfileUserId(null)}
                           onOpenShowtime={id => { setProfileUserId(null); openShowtime(id); }} />
      )}
    </div>
  );
}

function useJson(url) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let live = true;
    setData(null);
    fetch(url, { credentials: "include" })
      .then(r => (r.ok ? r.json() : { error: true }))
      .then(d => live && setData(d))
      .catch(() => live && setData({ error: true }));
    return () => { live = false; };
  }, [url]);
  return data;
}

function Members({ group, apiBase, viewerId, onOpen }) {
  const data = useJson(`${apiBase}/api/groups/${group.slug}/members`);
  if (!data) return <p className="pv-empty">Loading…</p>;
  if (data.error) return <p className="pv-empty">Couldn't load members right now.</p>;
  const active = data.filter(m => m.status === "active" && m.user)
    .sort((a, b) => (ROLE_ORDER[a.role] ?? 2) - (ROLE_ORDER[b.role] ?? 2) || a.user.name.localeCompare(b.user.name));
  return (
    <ul className="club-rows">
      {active.map(m => (
        <li key={m.id}>
          <button type="button" className="club-row clickable" onClick={() => onOpen(m.user.id)}>
            <Avatar user={m.user} size={38} />
            <span className="club-row-name">
              {m.user.name}{m.user.id === viewerId && <span className="club-you"> (you)</span>}
              {m.user.bio && <small className="club-row-sub">{m.user.bio}</small>}
            </span>
            {m.role !== "member" && <span className={`chip${m.role === "admin" ? " gold" : ""}`}>{roleLabel(m.role)}</span>}
          </button>
        </li>
      ))}
    </ul>
  );
}

function Leaderboard({ group, apiBase, viewerId, onOpen }) {
  const rows = useJson(`${apiBase}/api/groups/${group.id}/leaderboard`);
  if (!rows) return <p className="pv-empty">Loading…</p>;
  if (rows.error || !rows.length) {
    return <p className="pv-empty">No standings yet — vote in a scored poll or log a screening you went to. 🍿</p>;
  }
  return (
    <>
      <p className="pv-hint">Kernels from scored polls, then screenings attended.</p>
      <ol className="club-rows">
        {rows.map((r, i) => (
          <li key={r.user.id}>
            <button type="button" className={`club-row clickable${r.user.id === viewerId ? " me" : ""}`} onClick={() => onOpen(r.user.id)}>
              <span className="club-rank">{(r.kernels || r.attendance) && MEDALS[i] ? MEDALS[i] : i + 1}</span>
              <Avatar user={r.user} size={34} />
              <span className="club-row-name">{r.user.name}</span>
              <span className="club-score">
                <strong>🍿 {r.kernels}</strong>
                <small>{r.correct} correct · {r.attendance} attended</small>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </>
  );
}

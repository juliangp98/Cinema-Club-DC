import { useState, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { SectionTitle } from "../ui/PageHeader";
import Tabs from "../ui/Tabs";
import Avatar, { ClubBadge } from "../ui/Avatar";
import ClubSettings from "../components/ClubSettings";
import CalendarLinks from "../components/CalendarLinks";
import Feed from "./Feed";
import { ClubWeek } from "./DiscoverPage";
import { useShell } from "../shell/AppShell";
import useShowtimeSheet from "../shell/useShowtimeSheet";
import { roleLabel, runsClub } from "../roles";
import TheatreLink from "../ui/TheatreLink";
import { personPath } from "../ui/PersonLink";
import { GamesRail, GamesStrip } from "../ui/GamesSummary";
import ClubBoard from "../components/ClubBoard";
import { ClubStats, MembersStrip } from "../components/ClubOverview";
import { monthDay } from "../dates";
import { useJson, getJson, send } from "../api";
import { TourOffer } from "../ui/PageTourControls";
import "./Club.css";

const ROLE_ORDER = { admin: 0, organizer: 1, member: 2, viewer: 3 };

// The club's page (R6b; rebuilt in R15): who it is; an Overview (this week and
// recent activity, beside the members, the month's numbers and the games);
// members as tiles; the leaderboard by period; and settings for organizers
// (theatres, join requests, games) and admins (everything). ?tab= picks the
// tab, so the old /members and /leaderboard links land on theirs.
export default function ClubPage({ user, apiBase }) {
  const shell = useShell();
  const navigate = useNavigate();
  const group = shell?.group;
  const [params, setParams] = useSearchParams();
  const [theatreBySlug, setTheatreBySlug] = useState({});
  const isAdmin = shell?.role === "admin";
  const canManage = runsClub(shell?.role);
  const tabs = [{ key: "overview", label: "Overview" }, { key: "members", label: "Members" },
                { key: "leaderboard", label: "Leaderboard" }, ...(canManage ? [{ key: "settings", label: "Settings" }] : [])];
  const tab = tabs.some(t => t.key === params.get("tab")) ? params.get("tab") : "overview";
  const setTab = key => setParams(key === "overview" ? {} : { tab: key }, { replace: true });
  const { openShowtime, sheet } = useShowtimeSheet({ user, apiBase, groupId: group?.id });

  useEffect(() => {
    getJson(`${apiBase}/api/theatres`)
      .then(ts => setTheatreBySlug(Object.fromEntries(ts.map(t => [t.slug, t]))))
      .catch(() => {});
  }, [apiBase]);

  if (!group) {
    return (
      <div className="page narrow">
        <p className="pv-empty">You're not in a club yet. <Link to="/groups">Find or start one →</Link></p>
      </div>
    );
  }

  const theatres = (group.theatres || []).map(s => theatreBySlug[s] || { slug: s, name: s });
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
          {theatres.length > 0 && <p className="club-hero-theatres">{theatres.map(t => <TheatreLink key={t.slug} theatre={t} short />)}</p>}
        </div>
      </header>

      <TourOffer page="club" />
      <Tabs tabs={tabs} value={tab} onChange={setTab} label="Club" />
      <div role="tabpanel" className="club-panel">
        {tab === "overview" && <Overview group={group} apiBase={apiBase} user={user} shell={shell}
                                         openShowtime={openShowtime} setTab={setTab} />}
        {tab === "members" && (
          <>
            <Members group={group} apiBase={apiBase} viewerId={user.id} />
            <LeaveClub group={group} apiBase={apiBase} userId={user.id}
                       onLeft={async () => { await shell.refreshGroups?.(); navigate("/", { replace: true }); }} />
          </>
        )}
        {tab === "leaderboard" && <ClubBoard group={group} apiBase={apiBase} viewerId={user.id} />}
        {tab === "settings" && canManage && (
          <ClubSettings group={group} apiBase={apiBase} viewerId={user.id} isAdmin={isAdmin}
                        onChanged={() => shell.refreshGroups?.()}
                        onDeleted={async () => { await shell.refreshGroups?.(); navigate("/groups"); }} />
        )}
      </div>

      {sheet}
    </div>
  );
}

// The overview: what's on and what happened (main column) beside the club's
// people, numbers and games (side column; on phones the games come first).
function Overview({ group, apiBase, user, shell, openShowtime, setTab }) {
  const { data: play } = useJson(`${apiBase}/api/play?group_id=${group.id}`);
  const { data: stats } = useJson(`${apiBase}/api/groups/${group.id}/stats`);
  const { data: members } = useJson(`${apiBase}/api/groups/${group.slug}/members`);
  return (
    <div className="club-overview ui-split">
      <div className="club-main">
        <GamesStrip summary={play} className="club-strip" />
        <ClubWeek apiBase={apiBase} groupId={group.id} viewerId={user.id} onOpenShowtime={openShowtime}
                  onOpenActivity={shell.openActivity} />
        <SectionTitle link={{ to: "/feed", label: "See the full feed →" }}>Recent activity</SectionTitle>
        <div className="club-feed"><Feed user={user} apiBase={apiBase} groupId={group.id} limit={3} /></div>
        <SectionTitle>In your calendar</SectionTitle>
        <CalendarLinks apiBase={apiBase} clubId={group.id} />
      </div>
      <aside className="club-side ui-split-side sticky" aria-label="The club at a glance">
        <MembersStrip members={activeMembers(members)} onAll={() => setTab("members")} />
        <ClubStats stats={stats} onBoard={() => setTab("leaderboard")} />
        <div className="club-side-games"><GamesRail summary={play} /></div>
      </aside>
    </div>
  );
}

const activeMembers = data => (data || []).filter(m => m.status === "active" && m.user)
  .sort((a, b) => (ROLE_ORDER[a.role] ?? 2) - (ROLE_ORDER[b.role] ?? 2) || a.user.name.localeCompare(b.user.name));

// Members as poster-style tiles: picture, name, role, and how often they've
// been out this month (or when they last were).
function Members({ group, apiBase, viewerId }) {
  const { data, error } = useJson(`${apiBase}/api/groups/${group.slug}/members`);
  const { data: stats } = useJson(`${apiBase}/api/groups/${group.id}/stats`);
  if (error) return <p className="pv-empty">Couldn't load members right now.</p>;
  if (!data) return <p className="pv-empty">Loading…</p>;
  const stat = uid => {
    const s = stats?.members?.[uid];
    if (!s) return null;
    if (s.screenings) return `🎟️ ${s.screenings} this month`;
    return s.last_out ? `Last out ${monthDay(s.last_out)}` : "No screenings yet";
  };
  return (
    <ul className="club-tiles">
      {activeMembers(data).map(m => (
        <li key={m.id}>
          <Link className={`club-tile${m.user.id === viewerId ? " me" : ""}`} to={personPath(m.user.id)}>
            <Avatar user={m.user} size={72} />
            <span className="club-tile-name">{m.user.name}{m.user.id === viewerId && <span className="club-you"> (you)</span>}</span>
            <span className={`ui-badge${m.role === "admin" ? " gold" : m.role === "organizer" ? " go" : ""}`}>{roleLabel(m.role || "member")}</span>
            {stat(m.user.id) && <span className="club-tile-stat">{stat(m.user.id)}</span>}
          </Link>
        </li>
      ))}
    </ul>
  );
}

// Leave the club: your plans and history stay yours, but you stop seeing
// the club. The server keeps a club from losing its only admin.
export function LeaveClub({ group, apiBase, userId, onLeft }) {
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  async function leave() {
    if (!window.confirm(`Leave ${group.name}? You'll stop seeing its plans, feed and games. You can ask to join again later.`)) return;
    setBusy(true);
    setError(null);
    try {
      await send(`${apiBase}/api/groups/${group.slug}/members/${userId}`, "DELETE");
      onLeft();
    } catch (e) {
      setError(e.data?.error || "Couldn't leave right now — try again.");
    } finally { setBusy(false); }
  }
  return (
    <div className="club-leave" id="leave-club">
      <button type="button" className="btn btn-sm btn-ghost club-leave-btn" disabled={busy} onClick={leave}>Leave this club</button>
      {error && <p className="ui-hint" role="status">{error}</p>}
    </div>
  );
}

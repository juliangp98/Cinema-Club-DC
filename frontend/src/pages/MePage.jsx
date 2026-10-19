import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import Avatar from "../ui/Avatar";
import Panel from "../ui/Panel";
import { EditIcon, LogoutIcon, CompassIcon, HelpIcon, TheatreIcon } from "../ui/icons";
import { ClubBadge } from "../ui/Avatar";
import ProfileLists from "../components/ProfileLists";
import { useShell } from "../shell/AppShell";
import useShowtimeSheet from "../shell/useShowtimeSheet";
import { accountLabel } from "../accountLabel";
import MeSettings from "../components/MeSettings";
import Tabs from "../ui/Tabs";

// "Me": your profile, your lists, and your group's pages — one place to find
// what used to hide in the avatar and group dropdowns — and (7g) your
// Settings, as its second tab (?tab=settings).
const TABS = [{ key: "profile", label: "Profile" }, { key: "settings", label: "Settings" }];
export default function MePage({ user, apiBase, groupId }) {
  const { logout, group, startTour } = useShell();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "settings" ? "settings" : "profile";
  const setTab = key => setParams(key === "profile" ? {} : { tab: key }, { replace: true });
  const [listKey, setListKey] = useState(0);   // refresh lists after RSVP / check-in changes
  const { openShowtime, sheet } = useShowtimeSheet({
    user, apiBase, groupId, onChange: () => setListKey(k => k + 1),
  });

  return (
    <div className="page me-page">
      <PageHeader title="Me" tour="me" />
      <Tabs tabs={TABS} value={tab} onChange={setTab} label="Me" />
      {tab === "settings" ? <MeSettings user={user} apiBase={apiBase} /> : <>

      {user.is_guest && (
        <Panel tone="callout" title="Keep your profile"
               actions={<button className="btn btn-primary" onClick={() => navigate("/signin?next=%2Fme")}>Keep it</button>}>
          <p>This guest profile lives only in this browser and only you can see it. Add an email or Discord to keep your
             plans and watchlist on every device — and to join a club.</p>
        </Panel>
      )}

      <div className="ui-split" style={{ "--split-side": "360px" }}>
      <div className="me-main">
      <section className="me-card">
        <Avatar user={user} size={64} />
        <div className="me-card-text">
          <div className="me-name">{user.name}</div>
          <div className="me-sub">{accountLabel(user)}</div>
        </div>
        <div className="me-card-actions">
          <button className="btn" onClick={() => setTab("settings")}><EditIcon /> Settings</button>
          <button className="btn btn-ghost" onClick={logout}><LogoutIcon /> Sign out</button>
        </div>
      </section>

      <div id="me-lists"><SectionTitle>Your lists</SectionTitle></div>
      <ProfileLists userId={user.id} apiBase={apiBase} own onOpen={openShowtime}
                    onChange={() => setListKey(k => k + 1)} refreshKey={listKey} />
      </div>

      {/* Wide screens (7f): your calendar, club and the rest beside your lists. */}
      <aside className="ui-split-side me-side" aria-label="Calendar, club and help">

      {!user.is_guest && (
        <div className="me-block">
          <SectionTitle>In your calendar</SectionTitle>
          <p className="ui-hint">Your plans in Google, Apple or Outlook Calendar: <Link to="/me?tab=settings#me-calendar">subscribe in
            Settings → Connections</Link>.</p>
        </div>
      )}

      {!user.is_guest && groupId && (<>
      <div className="me-block">
        <SectionTitle>Your club</SectionTitle>
      </div>
      <div className="me-links">
        <button className="me-link" onClick={() => navigate("/club")}>
          {group && <ClubBadge group={group} size={28} />}
          <span>{group?.name || "Club page"}<small>Members, leaderboard and activity</small></span>
        </button>
        <button className="me-link" onClick={() => navigate("/theatres")}>
          <TheatreIcon /><span>Theatres<small>Every theatre's schedule, map and what's special there</small></span>
        </button>
        <button className="me-link" onClick={() => navigate("/groups")}>
          <CompassIcon /><span>Other clubs<small>Join or start another club</small></span>
        </button>
      </div>
      </>)}
      {!user.is_guest && !groupId && (
        <div className="me-links">
          <button className="me-link" onClick={() => navigate("/groups")}>
            <CompassIcon /><span>Find a club<small>See who's going, plan screenings, vote in polls</small></span>
          </button>
        </div>
      )}

      <div className="me-links tight">
        {!user.is_guest && (
          <button className="me-link" onClick={() => startTour?.()}>
            <CompassIcon /><span>Take the tour<small>A quick look around the site</small></span>
          </button>
        )}
        <button className="me-link" onClick={() => navigate("/help")}>
          <HelpIcon /><span>Help<small>How everything works, and answers to common questions</small></span>
        </button>
      </div>
      </aside>
      </div>

      </>}
      {sheet}
    </div>
  );
}

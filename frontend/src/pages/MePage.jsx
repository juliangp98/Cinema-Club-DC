import { useState } from "react";
import { useNavigate } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import Avatar from "../ui/Avatar";
import { EditIcon, LogoutIcon, CompassIcon } from "../ui/icons";
import { ClubBadge } from "../ui/Avatar";
import { WatchlistTab, GoingTab, HistoryTab } from "../components/UserProfileDrawer";
import UserProfileDrawer from "../components/UserProfileDrawer";
import { useShell } from "../shell/AppShell";
import useShowtimeSheet from "../shell/useShowtimeSheet";
import { accountLabel } from "../accountLabel";
import CalendarLinks from "../components/CalendarLinks";

const TABS = ["Watchlist", "Going", "History"];

// "Me": your profile, your lists, and your group's pages — one place to find
// what used to hide in the avatar and group dropdowns.
export default function MePage({ user, apiBase, groupId }) {
  const { editProfile, logout, group } = useShell();
  const navigate = useNavigate();
  const [tab, setTab] = useState("Watchlist");
  const [profileUserId, setProfileUserId] = useState(null);
  const [listKey, setListKey] = useState(0);   // refresh lists after RSVP / check-in changes
  const { openShowtime, sheet } = useShowtimeSheet({
    user, apiBase, groupId, onViewProfile: setProfileUserId, onChange: () => setListKey(k => k + 1),
  });

  return (
    <div className="page narrow">
      <PageHeader title="Me" />

      {user.is_guest && (
        <section className="join-club">
          <div>
            <span className="deco join-club-title">Keep your profile</span>
            <p>This guest profile lives only in this browser and only you can see it. Add an email or Discord to keep your
               plans and watchlist on every device — and to join a club.</p>
          </div>
          <button className="btn btn-primary" onClick={() => navigate("/signin?next=%2Fme")}>Keep it</button>
        </section>
      )}

      <section className="me-card">
        <Avatar user={user} size={64} />
        <div className="me-card-text">
          <div className="me-name">{user.name}</div>
          <div className="me-sub">{accountLabel(user)}</div>
        </div>
        <div className="me-card-actions">
          <button className="btn" onClick={editProfile}><EditIcon /> Edit profile</button>
          <button className="btn btn-ghost" onClick={logout}><LogoutIcon /> Sign out</button>
        </div>
      </section>

      <SectionTitle>Your lists</SectionTitle>
      <div className="profile-tabs" role="tablist">
        {TABS.map(t => (
          <button key={t} type="button" role="tab" aria-selected={tab === t}
                  className={`profile-tab${tab === t ? " active" : ""}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div className="profile-tab-panel" role="tabpanel" key={`${tab}-${listKey}`}>
        {tab === "Watchlist" && <WatchlistTab userId={user.id} apiBase={apiBase} onOpen={openShowtime} />}
        {tab === "Going" && <GoingTab userId={user.id} apiBase={apiBase} onOpen={openShowtime} />}
        {tab === "History" && (
          <HistoryTab userId={user.id} apiBase={apiBase} onOpen={openShowtime} onChange={() => setListKey(k => k + 1)} />
        )}
      </div>

      {!user.is_guest && (
        <div style={{ marginTop: "2rem" }}>
          <SectionTitle>In your calendar</SectionTitle>
          <p className="pv-hint">Subscribe once and your plans stay in sync with Google, Apple or Outlook Calendar.</p>
          <CalendarLinks apiBase={apiBase} />
        </div>
      )}

      {!user.is_guest && groupId && (<>
      <div style={{ marginTop: "2rem" }}>
        <SectionTitle>Your club</SectionTitle>
      </div>
      <div className="me-links">
        <button className="me-link" onClick={() => navigate("/club")}>
          {group && <ClubBadge group={group} size={28} />}
          <span>{group?.name || "Club page"}<small>Members, leaderboard and activity</small></span>
        </button>
        <button className="me-link" onClick={() => navigate("/groups")}>
          <CompassIcon /><span>Other clubs<small>Join or start another club</small></span>
        </button>
      </div>
      </>)}
      {!user.is_guest && !groupId && (
        <div className="me-links" style={{ marginTop: "2rem" }}>
          <button className="me-link" onClick={() => navigate("/groups")}>
            <CompassIcon /><span>Find a club<small>See who's going, plan screenings, vote in polls</small></span>
          </button>
        </div>
      )}

      {sheet}
      {profileUserId && (
        <UserProfileDrawer userId={profileUserId} viewerId={user.id} apiBase={apiBase}
                           onClose={() => setProfileUserId(null)}
                           onOpenShowtime={id => { setProfileUserId(null); openShowtime(id); }} />
      )}
    </div>
  );
}

import { createContext, useContext, useState, useCallback, useEffect, Suspense } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import GroupSwitcher from "../components/GroupSwitcher";
import lazyPage from "../lazyPage";
import Sheet from "../ui/Sheet";
import Loading from "../ui/Loading";
import Menu, { MenuItem, MenuDivider, MenuLabel } from "../ui/Menu";
import Avatar from "../ui/Avatar";
import { CalendarIcon, CompassIcon, FeedIcon, HelpIcon, PlayIcon, UserIcon, UsersIcon, EditIcon, LogoutIcon, TheatreIcon } from "../ui/icons";
import { useActivity, ActivityBell, ActivityPanel } from "./Activity";
import { accountLabel } from "../accountLabel";
import InstallPrompt from "./InstallPrompt";
import { clearCache, send } from "../api";

const ProfileEditor = lazyPage(() => import("../components/ProfileMenu"));   // opens on demand
const Tour = lazyPage(() => import("./Tour"));                                 // R11, on demand

// Everything signed-in pages share: the top bar (desktop nav, group switcher,
// the activity bell, your menu), the bottom tab bar on phones, the profile
// editor and the activity panel. Pages get at these through useShell()
// instead of each building its own header.
const ShellContext = createContext(null);
export const useShell = () => useContext(ShellContext);

// Discover is home (R3c). Visitors get the public pages; the Feed and Play
// need a club, Clubs is for finding one (R5a). Play (R10) is the games' home —
// trivia, bingo, polls (/polls lives under it), kernels. Phones show five
// tabs, so for club members Theatres steps off the tab bar there (every
// theatre name links to its page, and Discover and the Me page link to all).
const PUBLIC_NAV = [
  { to: "/", label: "Discover", icon: CompassIcon, end: true, also: "/browse" },
  { to: "/calendar", label: "Calendar", icon: CalendarIcon },
  { to: "/theatres", label: "Theatres", icon: TheatreIcon },
];
const FEED = { to: "/feed", label: "Feed", icon: FeedIcon };
const PLAY = { to: "/play", label: "Play", icon: PlayIcon, also: "/polls" };
const CLUB_NAV = [PUBLIC_NAV[0], PUBLIC_NAV[1], FEED, PLAY, PUBLIC_NAV[2]];
const CLUB_TABS = CLUB_NAV.filter(n => n.to !== "/theatres");
const NO_CLUB_NAV = [...PUBLIC_NAV, { to: "/groups", label: "Clubs", icon: UsersIcon }];

const linkClass = (base, also, pathname) => ({ isActive }) =>
  `${base}${isActive || (also && pathname.startsWith(also)) ? " active" : ""}`;

export default function AppShell({ user, setUser, apiBase, groupId, group, groups, setGroupId, refreshGroups }) {
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const NAV = !user || user.is_guest ? PUBLIC_NAV : groupId ? CLUB_NAV : NO_CLUB_NAV;
  const signInLink = `/signin?next=${encodeURIComponent(pathname + search)}`;
  const [editing, setEditing] = useState(false);
  const [touring, setTouring] = useState(false);

  // The welcome tour (R11): on its own once per account (new ones, and
  // everyone the first time it shipped); replayable from the menu and Help.
  useEffect(() => {
    if (!user || user.is_guest || user.tour_seen !== false || pathname.startsWith("/auth")) return undefined;
    const t = setTimeout(() => setTouring(true), 900);
    return () => clearTimeout(t);
  }, [user?.id, user?.tour_seen]);   // eslint-disable-line react-hooks/exhaustive-deps
  const finishTour = useCallback(() => {
    setTouring(false);
    if (user && user.tour_seen === false) {
      send(`${apiBase}/api/me/tour`).catch(() => {});
      setUser({ ...user, tour_seen: true });
    }
  }, [user, apiBase, setUser]);

  // A visitor's first RSVP / watchlist add / reaction makes a private guest
  // profile (R5b); returns the signed-in user either way, or null if refused.
  const ensureProfile = useCallback(async () => {
    if (user) return user;
    const u = (await send(`${apiBase}/api/auth/guest`).catch(() => null))?.user;
    if (!u) return null;
    setUser(u);
    return u;
  }, [user, apiBase, setUser]);

  const logout = useCallback(async () => {
    if (user?.is_guest && !window.confirm("Sign out of your guest profile? Your plans and watchlist can't be recovered "
                                          + "unless you keep the profile first (add an email or Discord).")) return;
    try {
      await send(`${apiBase}/api/auth/logout`).catch(() => {});
    } finally {
      clearCache();                   // nothing loaded while signed in stays around
      setUser(null);
      navigate("/", { replace: true });
    }
  }, [apiBase, setUser, navigate, user]);

  const activity = useActivity({ apiBase, groupId: user ? groupId : null, user });
  // A push about several alerts opens the bell (?alerts=1).
  useEffect(() => {
    if (!user || !new URLSearchParams(window.location.search).has("alerts")) return;
    activity.open("mine");
    window.history.replaceState(null, "", window.location.pathname);
  }, [user]);   // eslint-disable-line react-hooks/exhaustive-deps
  // Your role in the club you're viewing (R5c): read-only members see, but don't post.
  const role = group?.role || null;
  const canParticipate = !!groupId && role !== "viewer";
  const shell = { user, setUser, apiBase, groupId, group, role, canParticipate, setGroupId, refreshGroups, logout, ensureProfile,
                  editProfile: () => setEditing(true), startTour: () => setTouring(true),
                  openActivity: () => activity.open("club") };

  return (
    <ShellContext.Provider value={shell}>
      <div className="shell">
        <header className="topbar">
          <NavLink to="/" className="topbar-logo" aria-label="Cinema Club DC — home">
            <span className="deco">Cinema Club DC</span>
          </NavLink>
          <nav className="topbar-nav" aria-label="Main">
            {NAV.map(n => (
              <NavLink key={n.to} to={n.to} end={n.end} className={linkClass("topbar-link", n.also, pathname)}>{n.label}</NavLink>
            ))}
          </nav>
          <div className="topbar-spacer" />
          {user && groupId && <GroupSwitcher groups={groups} activeGroupId={groupId} setGroupId={setGroupId} />}
          {user && <ActivityBell unread={activity.unread} onOpen={activity.open} />}
          {!user && <Link className="btn btn-sm btn-primary topbar-signin" to={signInLink}>Sign in</Link>}
          {user && <Menu
            className="topbar-avatar"
            label="Your account"
            trigger={<Avatar user={user} size={32} />}
          >
            <MenuLabel>{user.name} · {accountLabel(user)}</MenuLabel>
            <MenuItem onSelect={() => navigate("/me")}><UserIcon /> {user.is_guest ? "Your plans & watchlist" : <>Your profile &amp; lists</>}</MenuItem>
            {user.is_guest && <MenuItem onSelect={() => navigate("/signin?next=%2Fme")}><EditIcon /> Keep your profile</MenuItem>}
            <MenuItem onSelect={() => setEditing(true)}><EditIcon /> Edit profile</MenuItem>
            {!user.is_guest && <MenuItem onSelect={() => setTouring(true)}><CompassIcon /> Take the tour</MenuItem>}
            <MenuItem onSelect={() => navigate("/help")}><HelpIcon /> Help</MenuItem>
            <MenuDivider />
            <MenuItem danger onSelect={logout}><LogoutIcon /> Sign out</MenuItem>
          </Menu>}
        </header>

        <main className="shell-main">
          <Suspense fallback={<div className="page"><Loading /></div>}><Outlet /></Suspense>
        </main>

        <nav className="tabbar" aria-label="Main">
          {[...(NAV === CLUB_NAV ? CLUB_TABS : NAV), user ? { to: "/me", label: "Me", icon: UserIcon } : { to: signInLink, label: "Sign in", icon: UserIcon }].map(({ to, label, icon: Icon, end, also }) => (
            <NavLink key={to} to={to} end={end} className={linkClass("tabbar-link", also, pathname)}>
              <Icon />{label}
            </NavLink>
          ))}
        </nav>

        <InstallPrompt />

        {touring && <Suspense fallback={null}><Tour inClub={!!groupId} onFinish={finishTour} /></Suspense>}

        {activity.isOpen && (
          <ActivityPanel user={user} apiBase={apiBase} groupId={groupId} activity={activity} />
        )}

        {editing && (
          <Sheet label="Edit profile" onClose={() => setEditing(false)}>
            <div className="profile-editor">
              <Suspense fallback={<Loading />}><ProfileEditor user={user} apiBase={apiBase} onUpdate={setUser} /></Suspense>
            </div>
          </Sheet>
        )}
      </div>
    </ShellContext.Provider>
  );
}

import { createContext, useContext, useState, useCallback } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import GroupSwitcher from "../components/GroupSwitcher";
import ProfileEditor from "../components/ProfileMenu";
import Sheet from "../ui/Sheet";
import Menu, { MenuItem, MenuDivider, MenuLabel } from "../ui/Menu";
import Avatar from "../ui/Avatar";
import { CalendarIcon, CompassIcon, PollIcon, UserIcon, UsersIcon, EditIcon, LogoutIcon } from "../ui/icons";
import { useActivity, ActivityBell, ActivityPanel } from "./Activity";
import { accountLabel } from "../accountLabel";

// Everything signed-in pages share: the top bar (desktop nav, group switcher,
// the activity bell, your menu), the bottom tab bar on phones, the profile
// editor and the activity panel. Pages get at these through useShell()
// instead of each building its own header.
const ShellContext = createContext(null);
export const useShell = () => useContext(ShellContext);

// Discover is home (R3c); the old Feed lives in the activity panel. Visitors
// get the public pages; Polls needs a club, Clubs is for finding one (R5a).
const PUBLIC_NAV = [
  { to: "/", label: "Discover", icon: CompassIcon, end: true, also: "/browse" },
  { to: "/calendar", label: "Calendar", icon: CalendarIcon },
];
const CLUB_NAV = [...PUBLIC_NAV, { to: "/polls", label: "Polls", icon: PollIcon }];
const NO_CLUB_NAV = [...PUBLIC_NAV, { to: "/groups", label: "Clubs", icon: UsersIcon }];

const linkClass = (base, also, pathname) => ({ isActive }) =>
  `${base}${isActive || (also && pathname.startsWith(also)) ? " active" : ""}`;

export default function AppShell({ user, setUser, apiBase, groupId, group, groups, setGroupId, refreshGroups }) {
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const NAV = !user || user.is_guest ? PUBLIC_NAV : groupId ? CLUB_NAV : NO_CLUB_NAV;
  const signInLink = `/signin?next=${encodeURIComponent(pathname + search)}`;
  const [editing, setEditing] = useState(false);

  // A visitor's first RSVP / watchlist add / reaction makes a private guest
  // profile (R5b); returns the signed-in user either way, or null if refused.
  const ensureProfile = useCallback(async () => {
    if (user) return user;
    const r = await fetch(`${apiBase}/api/auth/guest`, { method: "POST", credentials: "include" }).catch(() => null);
    if (!r?.ok) return null;
    const u = (await r.json()).user;
    setUser(u);
    return u;
  }, [user, apiBase, setUser]);

  const logout = useCallback(async () => {
    if (user?.is_guest && !window.confirm("Sign out of your guest profile? Your plans and watchlist can't be recovered "
                                          + "unless you keep the profile first (add an email or Discord).")) return;
    try {
      await fetch(`${apiBase}/api/auth/logout`, { method: "POST", credentials: "include" });
    } finally {
      setUser(null);
      navigate("/", { replace: true });
    }
  }, [apiBase, setUser, navigate, user]);

  const activity = useActivity({ apiBase, groupId: user ? groupId : null, user });
  // Your role in the club you're viewing (R5c): read-only members see, but don't post.
  const role = group?.role || null;
  const canParticipate = !!groupId && role !== "viewer";
  const shell = { user, setUser, apiBase, groupId, group, role, canParticipate, setGroupId, refreshGroups, logout, ensureProfile,
                  editProfile: () => setEditing(true),
                  openActivity: activity.open };

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
          {user && groupId && <ActivityBell unread={activity.unread} onOpen={activity.open} />}
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
            <MenuDivider />
            <MenuItem danger onSelect={logout}><LogoutIcon /> Sign out</MenuItem>
          </Menu>}
        </header>

        <main className="shell-main">
          <Outlet />
        </main>

        <nav className="tabbar" aria-label="Main">
          {[...NAV, user ? { to: "/me", label: "Me", icon: UserIcon } : { to: signInLink, label: "Sign in", icon: UserIcon }].map(({ to, label, icon: Icon, end, also }) => (
            <NavLink key={to} to={to} end={end} className={linkClass("tabbar-link", also, pathname)}>
              <Icon />{label}
            </NavLink>
          ))}
        </nav>

        {activity.isOpen && (
          <ActivityPanel user={user} apiBase={apiBase} groupId={groupId} onClose={activity.close} />
        )}

        {editing && (
          <Sheet label="Edit profile" onClose={() => setEditing(false)}>
            <div className="profile-editor">
              <ProfileEditor user={user} apiBase={apiBase} onUpdate={setUser} />
            </div>
          </Sheet>
        )}
      </div>
    </ShellContext.Provider>
  );
}

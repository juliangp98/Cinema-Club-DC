import { createContext, useContext, useState, useCallback } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import GroupSwitcher from "../components/GroupSwitcher";
import ProfileEditor from "../components/ProfileMenu";
import Sheet from "../ui/Sheet";
import Menu, { MenuItem, MenuDivider, MenuLabel } from "../ui/Menu";
import Avatar from "../ui/Avatar";
import { CalendarIcon, CompassIcon, PollIcon, UserIcon, EditIcon, LogoutIcon } from "../ui/icons";
import { useActivity, ActivityBell, ActivityPanel } from "./Activity";
import { accountLabel } from "../accountLabel";

// Everything signed-in pages share: the top bar (desktop nav, group switcher,
// the activity bell, your menu), the bottom tab bar on phones, the profile
// editor and the activity panel. Pages get at these through useShell()
// instead of each building its own header.
const ShellContext = createContext(null);
export const useShell = () => useContext(ShellContext);

// Discover is home (R3c); the old Feed lives in the activity panel.
const NAV = [
  { to: "/", label: "Discover", icon: CompassIcon, end: true, also: "/browse" },
  { to: "/calendar", label: "Calendar", icon: CalendarIcon },
  { to: "/polls", label: "Polls", icon: PollIcon },
];

const linkClass = (base, also, pathname) => ({ isActive }) =>
  `${base}${isActive || (also && pathname.startsWith(also)) ? " active" : ""}`;

export default function AppShell({ user, setUser, apiBase, groupId, setGroupId }) {
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [editing, setEditing] = useState(false);

  const logout = useCallback(async () => {
    try {
      await fetch(`${apiBase}/api/auth/logout`, { method: "POST", credentials: "include" });
    } finally {
      setUser(null);
      navigate("/", { replace: true });
    }
  }, [apiBase, setUser, navigate]);

  const activity = useActivity({ apiBase, groupId, user });
  const shell = { user, setUser, apiBase, groupId, setGroupId, logout, editProfile: () => setEditing(true),
                  openActivity: activity.open };
  // The calendar scrolls its own grid; every other page scrolls the main area.
  const fixed = pathname.startsWith("/calendar");

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
          <GroupSwitcher apiBase={apiBase} activeGroupId={groupId} setGroupId={setGroupId} />
          <ActivityBell unread={activity.unread} onOpen={activity.open} />
          <Menu
            className="topbar-avatar"
            label="Your account"
            trigger={<Avatar user={user} size={32} />}
          >
            <MenuLabel>{user.name} · {accountLabel(user)}</MenuLabel>
            <MenuItem onSelect={() => navigate("/me")}><UserIcon /> Your profile &amp; lists</MenuItem>
            <MenuItem onSelect={() => setEditing(true)}><EditIcon /> Edit profile</MenuItem>
            <MenuDivider />
            <MenuItem danger onSelect={logout}><LogoutIcon /> Sign out</MenuItem>
          </Menu>
        </header>

        <main className={`shell-main${fixed ? " fixed" : ""}`}>
          <Outlet />
        </main>

        <nav className="tabbar" aria-label="Main">
          {[...NAV, { to: "/me", label: "Me", icon: UserIcon }].map(({ to, label, icon: Icon, end, also }) => (
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

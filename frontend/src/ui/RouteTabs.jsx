import { NavLink } from "react-router-dom";

// Tabs that are pages: each tab is a link with its own address, so the back
// button works and a tab can be shared or linked from Discord and the bell.
// The profile-tabs look; on phones the row scrolls sideways. Play's Today,
// Challenges, Trivia… use it. tabs: [{ to, label, end? }] (`end`: active only
// on that exact path, for the first tab of a section).
export default function RouteTabs({ tabs, label }) {
  return (
    <nav className="profile-tabs route-tabs" aria-label={label}>
      {tabs.map(t => (
        <NavLink key={t.to} to={t.to} end={t.end} className={({ isActive }) => `profile-tab${isActive ? " active" : ""}`}>
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

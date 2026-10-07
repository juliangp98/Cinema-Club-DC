import { NavLink } from "react-router-dom";

const linkClass = ({ isActive }) => `main-nav-link${isActive ? " active" : ""}`;

// Feed / Calendar switch, shown in the header of both pages.
export default function MainNav() {
  return (
    <nav className="main-nav" aria-label="Main">
      <NavLink to="/" end className={linkClass}>Feed</NavLink>
      <NavLink to="/calendar" className={linkClass}>Calendar</NavLink>
    </nav>
  );
}

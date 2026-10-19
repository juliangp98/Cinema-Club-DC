// Small outline icons (24px grid, stroke = currentColor).
const base = { width: 24, height: 24, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
               strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };

export const CalendarIcon = () => (
  <svg {...base}><rect x="3" y="5" width="18" height="16" rx="2.5" /><path d="M3 10h18M8 3v4M16 3v4" /></svg>
);
export const TheatreIcon = () => (
  <svg {...base}><path d="M3 21V9l9-5 9 5v12" /><path d="M3 9h18" /><path d="M9 21v-5a3 3 0 0 1 6 0v5" /></svg>
);
export const PinIcon = () => (
  <svg {...base}><path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" /></svg>
);
export const FeedIcon = () => (
  <svg {...base}><path d="M9 6h11M9 12h11M9 18h11" /><circle cx="4.5" cy="6" r="1.2" /><circle cx="4.5" cy="12" r="1.2" />
    <circle cx="4.5" cy="18" r="1.2" /></svg>
);
export const HelpIcon = () => (
  <svg {...base}><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.6 2.6 0 0 1 5 .9c0 1.7-2.5 2.2-2.5 3.8" />
    <circle cx="12" cy="17.2" r="0.6" /></svg>
);
export const PlayIcon = () => (
  <svg {...base}><rect x="2.5" y="7" width="19" height="11" rx="5.5" /><path d="M7.5 10.5v4M5.5 12.5h4" />
    <circle cx="15.5" cy="11.5" r="0.9" /><circle cx="17.8" cy="13.8" r="0.9" /></svg>
);
export const UserIcon = () => (
  <svg {...base}><circle cx="12" cy="8" r="4" /><path d="M4 21c1.2-4 4.3-6 8-6s6.8 2 8 6" /></svg>
);
export const UsersIcon = () => (
  <svg {...base}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c.9-3.4 3.4-5.2 6.5-5.2s5.6 1.8 6.5 5.2" />
    <path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.9c2 .6 3.1 2.2 3.5 5.1" /></svg>
);
export const CompassIcon = () => (
  <svg {...base}><circle cx="12" cy="12" r="9" /><path d="m15.5 8.5-2 5-5 2 2-5 5-2Z" /></svg>
);
export const EditIcon = () => (
  <svg {...base}><path d="M4 20h4L19 9l-4-4L4 16v4Z" /><path d="m14 6 4 4" /></svg>
);
export const LogoutIcon = () => (
  <svg {...base}><path d="M10 4H5v16h5" /><path d="M14 8l4 4-4 4M18 12H9" /></svg>
);
export const BellIcon = () => (
  <svg {...base}><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15L6 16Z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></svg>
);

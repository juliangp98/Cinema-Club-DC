import Menu, { MenuItem, MenuLabel } from "../ui/Menu";
import { PinIcon } from "../ui/icons";

// The top bar's city pill (only when more than one city has theatres, and
// you're not looking at a club — a club's pages are its city's): which
// city's showtimes, theatres and clubs you see. Remembered on this device
// and, signed in, on your account.
export default function CityMenu({ cities, city, onPick }) {
  const current = cities.find(c => c.slug === city) || cities[0];
  return (
    <Menu label={`City: ${current.name}. Change it`} className="topbar-citymenu" triggerClassName="topbar-city"
          trigger={<><PinIcon /><span className="topbar-city-name">{current.short}</span><span className="caret">▾</span></>}>
      <MenuLabel>Showtimes in</MenuLabel>
      {cities.map(c => (
        <MenuItem key={c.slug} active={c.slug === current.slug} onSelect={() => onPick(c.slug)}>{c.name}</MenuItem>
      ))}
    </Menu>
  );
}

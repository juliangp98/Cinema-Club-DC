import { useShell } from "../shell/AppShell";

// A theatre's city, beside its name — only when the site has more than one
// city and it isn't the one you're looking at ("AFI Silver · DC" seen from Chicago).
export default function CityTag({ city }) {
  const shell = useShell();
  if (!shell?.multiCity || !city || city === shell.city) return null;
  const c = shell.cities.find(x => x.slug === city);
  return <span className="ui-badge city-tag" title={c?.name || city}>{c?.short || city}</span>;
}

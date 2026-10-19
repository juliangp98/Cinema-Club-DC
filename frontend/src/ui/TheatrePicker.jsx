import ToggleChip from "./ToggleChip";
import { byArea, byCity, cityOf } from "../places";

// Choosing theatres, the same everywhere (a club's theatres, starting a club,
// Your taste, the Where filter): the home city's theatres by area (DC /
// Maryland / Virginia), then — only if there are any — "Other cities", each
// city under its own heading so it's always clear which theatre is where.
// It opens by itself when one of them is chosen.
//   theatres  every theatre to offer ({slug, name, short_name, color, city, area_label})
//   home      the city to lead with (a club's, or yours)
//   cities    the site's cities (for names and area order)
//   isOn(slug), onToggle(slug), count(slug) — chosen, flip, a facet count
export default function TheatrePicker({ theatres, home, cities, isOn, onToggle, count, label = "Theatres" }) {
  const { home: here, others } = byCity(theatres, home, cities);
  const areas = byArea(here, cityOf(cities, home));
  const chip = t => (
    <ToggleChip key={t.slug} on={isOn(t.slug)} color={t.color} count={count?.(t.slug)} onClick={() => onToggle(t.slug)}>
      {t.short_name || t.name}
    </ToggleChip>
  );
  return (
    <div className="theatre-picker" role="group" aria-label={label}>
      {areas.map(([area, list]) => (
        <div key={area} className="theatre-picker-group">
          {areas.length > 1 && <span className="ui-group-label">{area}</span>}
          <div className="filter-chips">{list.map(chip)}</div>
        </div>
      ))}
      {others.length > 0 && (
        <details className="theatre-picker-others" open={others.some(([, list]) => list.some(t => isOn(t.slug)))}>
          <summary>Other cities</summary>
          {others.map(([city, list]) => (
            <div key={city.slug} className="theatre-picker-group">
              <span className="ui-group-label">{city.name}</span>
              <div className="filter-chips">{list.map(chip)}</div>
            </div>
          ))}
        </details>
      )}
    </div>
  );
}

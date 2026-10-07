import Sheet from "./Sheet";

// The one Filters sheet, shared by Browse and the Calendar: same filters,
// same URL parameter names (the server applies them the same way too).

export const FILTER_OPTIONS = {
  format: [["film", "On film (35/16/70mm)"], ["big", "Big screen (IMAX, 70mm, Dolby)"]],
  time: [["matinee", "Matinee (before 5pm)"], ["evening", "Evening (5–9pm)"], ["late", "Late night (9:30pm+)"]],
  rarity: [["rare", "Rare"], ["repertory", "Repertory (5+ years old)"], ["wide", "Wide release"]],
  club: [["going", "Friends going"], ["wanted", "The club wants it"], ["mine", "Mine"]],
  runtime: [["short", "Under 95 min"], ["long", "Over 2½ hours"]],
  mood: [["scare-me", "Scare me"], ["laugh", "Make me laugh"], ["mind-bender", "Mind-bender"], ["date-night", "Date night"],
         ["tissues", "Bring tissues"], ["feel-good", "Feel-good"], ["thrills", "Pure thrills"]],
};
export const FILTER_LABEL = Object.fromEntries(Object.entries(FILTER_OPTIONS)
  .flatMap(([k, opts]) => opts.map(([v, l]) => [`${k}:${v}`, l])));
export const listOf = v => (v ? v.split(",").filter(Boolean) : []);

/**
 * query: current params ({theatres: "afi,suns", genres: "horror", …})
 * multi: Set of keys that hold comma-separated lists
 * meta: {facets: {genres, theatres, decades}, regions: {slug: region}}
 * onToggle(key, value): add/remove (lists) or set/clear (single)
 * children: extra sections (e.g. the Calendar's "Who's going")
 * note: a line above the buttons (e.g. a link to Browse)
 * club: show "The club" filters (only in club mode)
 */
export default function FilterSheet({ query, multi, meta, theatreNames, total, onToggle, onClear, onClose, children, note, club = true }) {
  const Choice = ({ k, v, children: label, count }) => {
    const on = multi.has(k) ? listOf(query[k]).includes(v) : query[k] === v;
    return (
      <button type="button" className={`chip filter-choice${on ? " gold" : ""}`} aria-pressed={on} onClick={() => onToggle(k, v)}>
        {label}{count != null && <span className="mood-count">{count}</span>}
      </button>
    );
  };

  const facetGenres = Object.entries(meta?.facets?.genres || {}).sort((a, b) => b[1] - a[1]);
  for (const g of listOf(query.genres)) if (!facetGenres.some(([x]) => x === g)) facetGenres.push([g, 0]);
  const decades = Object.entries(meta?.facets?.decades || {}).sort((a, b) => b[0] - a[0]);
  const byRegion = {};
  for (const slug of Object.keys({ ...meta?.facets?.theatres, ...Object.fromEntries(listOf(query.theatres).map(s => [s, 0])) })) {
    const region = meta?.regions?.[slug] || "Other";
    (byRegion[region] = byRegion[region] || []).push(slug);
  }

  return (
    <Sheet label="Filters" onClose={onClose}>
      <div className="filters">
        <h2 className="ui-section-title"><span className="deco" style={{ fontSize: "1.3rem", color: "var(--amber)" }}>Filters</span></h2>
        {Object.keys(byRegion).length > 0 && (
          <fieldset><legend>Where</legend>
            {Object.entries(byRegion).map(([region, slugs]) => (
              <div key={region} className="filter-group">
                <span className="filter-sub">{region}</span>
                <div className="filter-chips">
                  {slugs.map(slug => (
                    <Choice key={slug} k="theatres" v={slug} count={meta?.facets?.theatres?.[slug]}>{theatreNames[slug] || slug}</Choice>
                  ))}
                </div>
              </div>
            ))}
          </fieldset>
        )}
        {facetGenres.length > 0 && (
          <fieldset><legend>Genre</legend>
            <div className="filter-chips">
              {facetGenres.map(([g, n]) => <Choice key={g} k="genres" v={g} count={n}>{g}</Choice>)}
            </div>
          </fieldset>
        )}
        <fieldset><legend>Mood</legend>
          <div className="filter-chips">{FILTER_OPTIONS.mood.map(([v, l]) => <Choice key={v} k="mood" v={v}>{l}</Choice>)}</div>
        </fieldset>
        {decades.length > 0 && (
          <fieldset><legend>Decade</legend>
            <div className="filter-chips">{decades.map(([d, n]) => <Choice key={d} k="decade" v={d} count={n}>{d}s</Choice>)}</div>
          </fieldset>
        )}
        {["format", "time", "rarity", ...(club ? ["club"] : []), "runtime"].map(k => (
          <fieldset key={k}><legend>{{ format: "Format", time: "Time of day", rarity: "Rarity", club: "The club", runtime: "Length" }[k]}</legend>
            <div className="filter-chips">{FILTER_OPTIONS[k].map(([v, l]) => <Choice key={v} k={k} v={v}>{l}</Choice>)}</div>
          </fieldset>
        ))}
        {children}
        {note && <p className="filter-note">{note}</p>}
        <div className="filters-foot">
          <button className="btn btn-ghost" onClick={onClear}>Clear all</button>
          <button className="btn btn-primary" onClick={onClose}>
            Show {total ?? 0} film{total === 1 ? "" : "s"}
          </button>
        </div>
      </div>
    </Sheet>
  );
}

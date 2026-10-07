import { useState, useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import PosterCard from "../ui/PosterCard";
import SearchBox from "../ui/SearchBox";
import Sheet from "../ui/Sheet";
import Menu, { MenuItem } from "../ui/Menu";
import "./DiscoverPage.css";

// Every filter lives in the URL, so any view is a shareable link (and the
// bot's /find answers can link straight to the same view).
const KEYS = ["when", "from", "to", "theatres", "regions", "genres", "decade", "format", "time",
              "rarity", "club", "runtime", "mood", "shelf", "q", "sort"];
const MULTI = new Set(["theatres", "regions", "genres", "format"]);

const WHEN = [["tonight", "Tonight"], ["tomorrow", "Tomorrow"], ["weekend", "This weekend"],
              ["week", "7 days"], ["2weeks", "2 weeks"], ["month", "30 days"]];
const SORTS = [["soonest", "Soonest"], ["rarest", "Rarest"], ["wanted", "Most wanted"], ["critics", "Top rated"], ["title", "A–Z"]];
const OPTIONS = {
  format: [["film", "On film (35/16/70mm)"], ["big", "Big screen (IMAX, 70mm, Dolby)"]],
  time: [["matinee", "Matinee (before 5pm)"], ["evening", "Evening (5–9pm)"], ["late", "Late night (9:30pm+)"]],
  rarity: [["rare", "Rare"], ["repertory", "Repertory (5+ years old)"], ["wide", "Wide release"]],
  club: [["going", "Friends going"], ["wanted", "The club wants it"], ["mine", "Mine"]],
  runtime: [["short", "Under 95 min"], ["long", "Over 2½ hours"]],
  mood: [["scare-me", "Scare me"], ["laugh", "Make me laugh"], ["mind-bender", "Mind-bender"], ["date-night", "Date night"],
         ["tissues", "Bring tissues"], ["feel-good", "Feel-good"], ["thrills", "Pure thrills"]],
};
const LABEL = Object.fromEntries(Object.entries(OPTIONS).flatMap(([k, opts]) => opts.map(([v, l]) => [`${k}:${v}`, l])));

const listOf = v => (v ? v.split(",").filter(Boolean) : []);

export default function BrowsePage({ apiBase, groupId }) {
  const [params, setParams] = useSearchParams();
  const [films, setFilms] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [theatreNames, setTheatreNames] = useState({});
  const [filtersOpen, setFiltersOpen] = useState(false);

  const query = useMemo(() => {
    const q = {};
    for (const k of KEYS) if (params.get(k)) q[k] = params.get(k);
    if (!q.when && !q.from) q.when = "week";
    return q;
  }, [params]);
  const qs = new URLSearchParams(query).toString();

  useEffect(() => {
    fetch(`${apiBase}/api/theatres`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : []))
      .then(ts => setTheatreNames(Object.fromEntries(ts.map(t => [t.slug, t.short_name || t.name]))))
      .catch(() => {});
  }, [apiBase]);

  useEffect(() => {
    let live = true;
    setLoading(true);
    fetch(`${apiBase}/api/discover/browse?group_id=${groupId}&${qs}`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(d => { if (live) { setFilms(d.films); setMeta(d); setFailed(false); } })
      .catch(() => { if (live) { setFilms([]); setMeta(null); setFailed(true); } })
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [apiBase, groupId, qs]);

  async function loadMore() {
    const r = await fetch(`${apiBase}/api/discover/browse?group_id=${groupId}&${qs}&offset=${meta.next_offset}`,
                          { credentials: "include" }).catch(() => null);
    if (!r?.ok) return;
    const d = await r.json();
    setFilms(prev => [...prev, ...d.films]);
    setMeta(d);
  }

  function set(key, value) {
    const next = new URLSearchParams(params);
    if (MULTI.has(key)) {
      const cur = listOf(next.get(key));
      const updated = cur.includes(value) ? cur.filter(v => v !== value) : [...cur, value];
      updated.length ? next.set(key, updated.join(",")) : next.delete(key);
    } else if (value == null || next.get(key) === value) {
      next.delete(key);
    } else {
      next.set(key, value);
    }
    setParams(next, { replace: true });
  }
  const clearAll = () => setParams(new URLSearchParams(query.when ? { when: query.when } : {}), { replace: true });

  // Active filters as removable chips (not when / q / sort, which have their own controls).
  const active = [];
  for (const k of KEYS) {
    if (["when", "from", "to", "q", "sort"].includes(k) || !query[k]) continue;
    for (const v of MULTI.has(k) ? listOf(query[k]) : [query[k]]) {
      const label = k === "theatres" ? (theatreNames[v] || v) : k === "decade" ? `${v}s`
        : k === "shelf" ? (meta?.title || v) : LABEL[`${k}:${v}`] || v.replace(/\b\w/g, c => c.toUpperCase());
      active.push({ k, v, label });
    }
  }
  const nFilters = active.length;
  const title = meta?.title || (query.q ? `“${query.q}”` : "Browse");
  const whenLabel = WHEN.find(([k]) => k === query.when)?.[1] || "Custom dates";

  const facetGenres = Object.entries(meta?.facets.genres || {}).sort((a, b) => b[1] - a[1]);
  for (const g of listOf(query.genres)) if (!facetGenres.some(([x]) => x === g)) facetGenres.push([g, 0]);
  const decades = Object.entries(meta?.facets.decades || {}).sort((a, b) => b[0] - a[0]);
  const byRegion = {};
  for (const slug of Object.keys({ ...meta?.facets.theatres, ...Object.fromEntries(listOf(query.theatres).map(s => [s, 0])) })) {
    const region = meta?.regions?.[slug] || "Other";
    (byRegion[region] = byRegion[region] || []).push(slug);
  }

  const Choice = ({ k, v, children, count }) => {
    const on = MULTI.has(k) ? listOf(query[k]).includes(v) : query[k] === v;
    return (
      <button type="button" className={`chip filter-choice${on ? " gold" : ""}`} aria-pressed={on} onClick={() => set(k, v)}>
        {children}{count != null && <span className="mood-count">{count}</span>}
      </button>
    );
  };

  return (
    <div className="page browse">
      <PageHeader title={title} back={{ to: "/discover", label: "Discover" }} />
      <SearchBox initial={query.q || ""} onSearch={q => set("q", q || null)} />

      <div className="browse-when" role="group" aria-label="When">
        {WHEN.map(([k, label]) => <Choice key={k} k="when" v={k}>{label}</Choice>)}
      </div>

      <div className="browse-bar">
        <button className="btn btn-sm" onClick={() => setFiltersOpen(true)}>
          Filters{nFilters ? ` (${nFilters})` : ""}
        </button>
        <Menu label="Sort" triggerClassName="btn btn-sm" align="start"
              trigger={<>Sort: {SORTS.find(([k]) => k === (query.sort || (query.shelf === "rare" ? "rarest" : "soonest")))?.[1] || "Soonest"} ▾</>}>
          {SORTS.map(([k, label]) => (
            <MenuItem key={k} active={query.sort === k} onSelect={() => set("sort", k)}>{label}</MenuItem>
          ))}
        </Menu>
        <span className="browse-count">
          {loading ? "Loading…" : `${meta?.total ?? 0} film${meta?.total === 1 ? "" : "s"} · ${whenLabel}`}
        </span>
      </div>

      {active.length > 0 && (
        <div className="browse-active">
          {active.map(a => (
            <button key={`${a.k}:${a.v}`} className="chip gold" onClick={() => set(a.k, MULTI.has(a.k) ? a.v : null)}
                    aria-label={`Remove ${a.label}`}>
              {a.label} ×
            </button>
          ))}
          <button className="chip" onClick={clearAll}>Clear all</button>
        </div>
      )}

      {failed ? (
        <div className="discover-empty"><p>Couldn't load films right now — try again in a moment.</p></div>
      ) : !loading && films.length === 0 ? (
        <div className="discover-empty">
          <p>Nothing matches. Try a wider window or fewer filters.</p>
          <div className="browse-when">
            {query.when !== "month" && <button className="btn btn-sm" onClick={() => set("when", "month")}>Next 30 days</button>}
            {nFilters > 0 && <button className="btn btn-sm" onClick={clearAll}>Clear filters</button>}
          </div>
        </div>
      ) : (
        <div className="poster-grid">
          {films.map(c => <PosterCard key={c.movie.id} card={c} />)}
        </div>
      )}
      {meta?.next_offset != null && !loading && (
        <div className="browse-more"><button className="btn" onClick={loadMore}>Load more</button></div>
      )}

      {filtersOpen && (
        <Sheet label="Filters" onClose={() => setFiltersOpen(false)}>
          <div className="filters">
            <h2 className="ui-section-title"><span className="deco" style={{ fontSize: "1.3rem", color: "var(--amber)" }}>Filters</span></h2>
            {Object.keys(byRegion).length > 0 && (
              <fieldset><legend>Where</legend>
                {Object.entries(byRegion).map(([region, slugs]) => (
                  <div key={region} className="filter-group">
                    <span className="filter-sub">{region}</span>
                    <div className="filter-chips">
                      {slugs.map(slug => (
                        <Choice key={slug} k="theatres" v={slug} count={meta?.facets.theatres[slug]}>{theatreNames[slug] || slug}</Choice>
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
              <div className="filter-chips">{OPTIONS.mood.map(([v, l]) => <Choice key={v} k="mood" v={v}>{l}</Choice>)}</div>
            </fieldset>
            {decades.length > 0 && (
              <fieldset><legend>Decade</legend>
                <div className="filter-chips">{decades.map(([d, n]) => <Choice key={d} k="decade" v={d} count={n}>{d}s</Choice>)}</div>
              </fieldset>
            )}
            {["format", "time", "rarity", "club", "runtime"].map(k => (
              <fieldset key={k}><legend>{{ format: "Format", time: "Time of day", rarity: "Rarity", club: "The club", runtime: "Length" }[k]}</legend>
                <div className="filter-chips">{OPTIONS[k].map(([v, l]) => <Choice key={v} k={k} v={v}>{l}</Choice>)}</div>
              </fieldset>
            ))}
            <div className="filters-foot">
              <button className="btn btn-ghost" onClick={clearAll}>Clear all</button>
              <button className="btn btn-primary" onClick={() => setFiltersOpen(false)}>
                Show {meta?.total ?? 0} film{meta?.total === 1 ? "" : "s"}
              </button>
            </div>
          </div>
        </Sheet>
      )}
    </div>
  );
}

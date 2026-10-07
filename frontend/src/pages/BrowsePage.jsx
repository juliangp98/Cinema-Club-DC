import { useState, useEffect, useMemo } from "react";
import { useSearchParams, useLocation } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import PosterCard from "../ui/PosterCard";
import SearchBox from "../ui/SearchBox";
import FilterSheet, { FILTER_LABEL as LABEL, listOf } from "../ui/FilterSheet";
import Menu, { MenuItem } from "../ui/Menu";
import "./DiscoverPage.css";
import { groupParam } from "../scope";

// Every filter lives in the URL, so any view is a shareable link (and the
// bot's /find answers can link straight to the same view).
const KEYS = ["when", "from", "to", "theatres", "regions", "genres", "decade", "format", "time",
              "rarity", "club", "runtime", "mood", "shelf", "q", "sort"];
const MULTI = new Set(["theatres", "regions", "genres", "format"]);

const WHEN = [["tonight", "Tonight"], ["tomorrow", "Tomorrow"], ["weekend", "This weekend"],
              ["week", "7 days"], ["2weeks", "2 weeks"], ["month", "30 days"]];
const SORTS = [["soonest", "Soonest"], ["rarest", "Rarest"], ["wanted", "Most wanted"], ["critics", "Top rated"], ["title", "A–Z"]];


export default function BrowsePage({ apiBase, groupId }) {
  const [params, setParams] = useSearchParams();
  const searchNote = useLocation().state?.searchNote;     // what ✨ AI search read the request as
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
    fetch(`${apiBase}/api/discover/browse?${groupParam(groupId)}${qs}`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(d => { if (live) { setFilms(d.films); setMeta(d); setFailed(false); } })
      .catch(() => { if (live) { setFilms([]); setMeta(null); setFailed(true); } })
      .finally(() => live && setLoading(false));
    return () => { live = false; };
  }, [apiBase, groupId, qs]);

  async function loadMore() {
    const r = await fetch(`${apiBase}/api/discover/browse?${groupParam(groupId)}${qs}&offset=${meta.next_offset}`,
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
  // A picked suggestion adds to the filters; ✨ AI search replaces them.
  function applySearch(picked, { replace = false, note } = {}) {
    const next = new URLSearchParams(replace ? {} : params);
    for (const [k, v] of Object.entries(picked)) {
      if (MULTI.has(k) && !replace) {
        const cur = listOf(next.get(k));
        if (!cur.includes(v)) next.set(k, [...cur, v].join(","));
      } else next.set(k, v);
    }
    setParams(next, { replace: true, state: note ? { searchNote: note } : undefined });
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
      <PageHeader title={title} back={{ to: "/", label: "Discover" }} />
      <SearchBox initial={query.q || ""} apiBase={apiBase} groupId={groupId} showNote={false}
                 onSearch={q => set("q", q || null)} onApply={applySearch} />
      {searchNote && <p className="searchbox-note browse-search-note" role="status">{searchNote}</p>}

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
        <FilterSheet query={query} multi={MULTI} meta={meta} theatreNames={theatreNames} total={meta?.total} club={!!groupId}
                     onToggle={set} onClear={clearAll} onClose={() => setFiltersOpen(false)} />
      )}
    </div>
  );
}

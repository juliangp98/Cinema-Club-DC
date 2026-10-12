import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import Loading, { LoadError } from "../ui/Loading";
import { DoubleCard, SpotlightCard } from "./DiscoverPage";
import { dayDate as dayLabel } from "../dates";
import { useJson } from "../api";
import { groupParam } from "../scope";
import "./DiscoverPage.css";

// Discover's See-all pages (R7b): every Spotlight, every double bill. Both
// can be narrowed to an area or one theatre, kept in the URL (?regions= /
// ?theatres=) like Browse, so a theatre page's "See all" lands pre-filtered.

const REGIONS = [["dc", "DC"], ["maryland", "Maryland"], ["virginia", "Virginia"]];

function useScope(apiBase) {
  const [params, setParams] = useSearchParams();
  const theatres = useJson(`${apiBase}/api/theatres`).data || [];
  const scope = { theatres: params.get("theatres") || "", regions: params.get("regions") || "" };
  const set = next => setParams(Object.fromEntries(Object.entries(next).filter(([, v]) => v)), { replace: true });
  const query = new URLSearchParams(Object.entries(scope).filter(([, v]) => v)).toString();
  const browseScope = query ? `&${query}` : "";
  const named = theatres.find(t => t.slug === scope.theatres);
  const label = named ? `at ${named.name}` : scope.regions ? `in ${REGIONS.find(([k]) => k === scope.regions)?.[1] || scope.regions}` : "";
  const bar = (
    <div className="more-scope" role="group" aria-label="Where">
      <button type="button" className={`chip filter-choice${!scope.theatres && !scope.regions ? " gold" : ""}`} onClick={() => set({})}>Everywhere</button>
      {REGIONS.map(([k, name]) => (
        <button key={k} type="button" className={`chip filter-choice${scope.regions === k && !scope.theatres ? " gold" : ""}`}
                onClick={() => set({ regions: k })}>{name}</button>
      ))}
      <select className="more-scope-theatre" value={scope.theatres} aria-label="Theatre"
              onChange={e => set({ theatres: e.target.value })}>
        <option value="">Any theatre</option>
        {theatres.map(t => <option key={t.slug} value={t.slug}>{t.name}</option>)}
      </select>
    </div>
  );
  return { query, browseScope, label, bar };
}

export function SpotlightsPage({ apiBase, groupId }) {
  const { query, browseScope, label, bar } = useScope(apiBase);
  const [role, setRole] = useState("all");
  const { data, error, reload } = useJson(`${apiBase}/api/discover/spotlights?${groupParam(groupId)}${query}`);
  const all = data?.spotlights || [];
  const shown = role === "all" ? all : all.filter(sp => sp.role === role);
  return (
    <div className="page discover-more">
      <PageHeader title="Spotlights" back={{ to: "/", label: "Discover" }}
                  subtitle={`Directors and stars with several films playing in the next 30 days${label ? ` ${label}` : ""}. Pick one to see them all.`} />
      {bar}
      <div className="more-scope" role="group" aria-label="Who">
        {[["all", "Everyone"], ["director", "Directors"], ["actor", "Actors"]].map(([k, name]) => (
          <button key={k} type="button" className={`chip filter-choice${role === k ? " gold" : ""}`} onClick={() => setRole(k)}>
            {name}{data && <span className="mood-count">{k === "all" ? all.length : all.filter(sp => sp.role === k).length}</span>}
          </button>
        ))}
      </div>
      {!data ? (error ? <LoadError what="the spotlights" onRetry={reload} /> : <Loading context="discover" />)
        : !shown.length ? <p className="pv-empty">No one has several films playing {label || "right now"} — try somewhere else.</p>
        : <div className="spotlights wide">{shown.map(sp => <SpotlightCard key={`${sp.role}:${sp.name}`} sp={sp} scope={browseScope} posters={5} />)}</div>}
    </div>
  );
}

export function DoublesPage({ apiBase, groupId }) {
  const { query, label, bar } = useScope(apiBase);
  const { data, error, reload } = useJson(`${apiBase}/api/discover/doubles?${groupParam(groupId)}${query}`);
  const days = [];
  for (const d of data?.doubles || []) {
    const day = dayLabel(d.first.next.start_time);
    if (days.at(-1)?.day !== day) days.push({ day, items: [] });
    days.at(-1).items.push(d);
  }
  const n = data?.doubles?.length || 0;
  return (
    <div className="page discover-more">
      <PageHeader title="Double features" back={{ to: "/", label: "Discover" }}
                  subtitle={`Two films, one theatre, one evening${data ? ` — ${n} double bill${n === 1 ? "" : "s"}` : ""} in the next six weeks${label ? ` ${label}` : ""}.`} />
      {bar}
      {!data ? (error ? <LoadError what="the double features" onRetry={reload} /> : <Loading context="discover" />)
        : !n ? <p className="pv-empty">No double bills {label || "coming up"} yet — theatres add showings every week.</p>
        : days.map(({ day, items }) => (
          <section key={day} className="shelf">
            <SectionTitle>{day}</SectionTitle>
            <div className="doubles">{items.map((d, i) => <DoubleCard key={i} d={d} showDay={false} />)}</div>
          </section>
        ))}
    </div>
  );
}

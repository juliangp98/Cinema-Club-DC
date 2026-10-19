import { Link, useParams, useSearchParams } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import PosterCard from "../ui/PosterCard";
import Poster from "../ui/Poster";
import Loading, { LoadError } from "../ui/Loading";
import { Shelf, DoubleFeatures, Spotlights, Announced, LAYOUT } from "./DiscoverPage";
import { Fragment, useEffect } from "react";
import { useJson, hideFilm } from "../api";
import { useShell } from "../shell/AppShell";
import { groupParam } from "../scope";
import { TheatreNotes } from "../ui/ScreeningNotes";
import "./DiscoverPage.css";
import "./Theatres.css";
import { dayShortTime } from "../dates";
import TicketChips, { AnnouncedCard } from "../ui/TicketChips";
import usePageMeta, { theatreLd } from "../seo";
import { DEFAULT_CITY, byArea, byCity, cityOf } from "../places";

const dayTime = dayShortTime;

// Every theatre we follow (R7b), by area: what's on at each (its most
// interesting films first), how many films and rare ones, film formats,
// tonight, and the next showing. Your city first; with more than one city,
// each other city after it, by area too.
export function TheatresPage({ apiBase }) {
  const { data: list, error, reload } = useJson(`${apiBase}/api/theatres-overview`);
  const shell = useShell() || {};
  const forYou = useJson(shell.user ? `${apiBase}/api/for-you/theatres?${groupParam(shell.groupId)}` : null);
  useEffect(() => { if (shell.tasteVersion) forYou.reload(); }, [shell.tasteVersion]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (error && !list) return <div className="page"><LoadError what="the theatres" onRetry={reload} /></div>;
  if (!list) return <div className="page"><Loading context="theatre" /></div>;

  const cities = shell.cities || [];
  const homeSlug = shell.city || DEFAULT_CITY;
  const home = cityOf(cities, homeSlug);
  const { home: here, others } = byCity(list, homeSlug, cities);
  const films = new Set(here.flatMap(t => t.preview.posters.map(p => p.id))).size;
  const tonight = here.reduce((n, t) => n + t.preview.tonight, 0);
  const cards = theatres => (
    <div className="theatre-cards">{theatres.map(t => <TheatreCard key={t.slug} t={t} forYou={forYou.data?.[t.slug]} />)}</div>
  );
  const elsewhere = others.reduce((n, [, ts]) => n + ts.length, 0);
  return (
    <div className="page theatres">
      <PageHeader title="Theatres" meta={[{ icon: "🎭", label: `${here.length} ${home ? `${home.phrase} ` : ""}theatres` },
                                          tonight > 0 && { icon: "🌙", label: `${tonight} showing${tonight === 1 ? "" : "s"} tonight`, gold: true, to: "/calendar" },
                                          elsewhere > 0 && { label: `+${elsewhere} in other cities` },
                                          { label: "Browse everything on →", to: "/browse?when=week", more: true }]} />
      {byArea(here, home).map(([area, theatres]) => (
        <section key={area} className="theatres-region">
          <SectionTitle>{area}</SectionTitle>
          {cards(theatres)}
        </section>
      ))}
      {others.map(([city, theatres]) => (
        <section key={city.slug} className="theatres-region theatres-city" id={`city-${city.slug}`}>
          <SectionTitle>{city.name}</SectionTitle>
          {byArea(theatres, city).map(([area, list]) => (
            <Fragment key={area}>
              <p className="ui-group-label theatres-area">{area}</p>
              {cards(list)}
            </Fragment>
          ))}
        </section>
      ))}
      {films === 0 && <p className="pv-empty">Nothing's scheduled at any theatre right now — check back soon.</p>}
    </div>
  );
}

function TheatreCard({ t, forYou }) {
  const p = t.preview;
  return (
    <article className="theatre-card" style={{ "--tcolor": t.color }}>
      <Link to={`/theatres/${t.slug}`} className="theatre-card-head">
        <span className="theatre-card-dot" aria-hidden="true" />
        <span className="theatre-card-name">{t.name}</span>
        {p.tonight > 0 && <span className="ui-badge solid">{p.tonight} tonight</span>}
      </Link>
      <p className="theatre-card-meta">
        {p.film_count ? `${p.film_count} film${p.film_count === 1 ? "" : "s"} in the next two weeks` : "Nothing scheduled right now"}
        {p.rare > 0 && <> · <span className="theatre-card-rare">{p.rare} rare</span></>}
        {forYou > 0 && <Link to={`/theatres/${t.slug}#shelf-for-you`} className="chip gold">✨ {forYou} for you</Link>}
        {p.formats.map(f => <span key={f} className="chip theatre-card-format">{f}</span>)}
      </p>
      {p.posters.length > 0 && (
        <div className="theatre-card-posters">
          {p.posters.map(m => (
            <Link key={m.id} to={`/films/${m.id}`} title={m.year ? `${m.title} (${m.year})` : m.title}>
              <Poster movie={m} className="theatre-card-poster" />
            </Link>
          ))}
        </div>
      )}
      <div className="theatre-card-foot">
        {p.next ? <span className="theatre-card-next">Next: {dayTime(p.next.start_time)} · {p.next.title}</span>
          : <span className="theatre-card-next">{t.address}</span>}
        <Link className="btn btn-sm" to={`/theatres/${t.slug}`}>See what's on →</Link>
      </div>
    </article>
  );
}

// One theatre (R7b, public): where it is (with a map), then the Discover page
// for just this theatre — rare gems, double bills, spotlights and every other
// shelf — and everything playing in the next month.
export function TheatrePage({ apiBase, groupId }) {
  const { slug } = useParams();
  const info = useJson(`${apiBase}/api/theatres/${slug}`);
  const disc = useJson(`${apiBase}/api/discover?${groupParam(groupId)}theatres=${slug}`);
  const shell = useShell() || {};
  useEffect(() => { if (shell.tasteVersion) disc.reload(); }, [shell.tasteVersion]);   // eslint-disable-line react-hooks/exhaustive-deps
  const [params, setParams] = useSearchParams();
  const tickets = params.get("tickets");
  const all = useJson(`${apiBase}/api/discover/browse?${groupParam(groupId)}theatres=${slug}&when=month&sort=soonest${tickets ? `&tickets=${tickets}` : ""}`);
  const setTickets = v => setParams(prev => { const n = new URLSearchParams(prev); v ? n.set("tickets", v) : n.delete("tickets"); return n; }, { replace: true });
  const t = info.data;
  usePageMeta(() => t && {
    title: t.name, path: `/theatres/${t.slug}`, jsonLd: theatreLd(t),
    description: `What's on at ${t.name}${t.address ? `, ${t.address}` : ""}: ${t.films ? `${t.films} film${t.films === 1 ? "" : "s"} in the next month` : "showtimes"}, a map, and what's special there.`,
  }, [t]);

  if (info.error?.status === 404) {
    return (
      <div className="page">
        <PageHeader title="Theatre not found" back={{ to: "/theatres", label: "Theatres" }} />
        <p className="pv-empty">We don't follow that theatre (any more). <Link to="/theatres">See all theatres →</Link></p>
      </div>
    );
  }
  if (info.error && !t) return <div className="page"><LoadError what="this theatre" onRetry={info.reload} /></div>;
  if (!t) return <div className="page"><Loading context="theatre" /></div>;

  const scope = `&theatres=${slug}`;
  const query = encodeURIComponent(`${t.name}, ${t.address || ""}`);
  const hasMap = t.lat != null && t.lon != null;
  const box = hasMap ? [t.lon - 0.009, t.lat - 0.005, t.lon + 0.009, t.lat + 0.005].map(n => n.toFixed(5)).join(",") : "";

  const d = disc.data;
  const byKey = Object.fromEntries((d?.shelves || []).map(s => [s.key, s]));
  const sections = [];
  for (const key of LAYOUT) {
    if (key === "@announced" && d?.announced?.length) sections.push(<Announced key={key} items={d.announced} />);
    else if (key === "@doubles" && d?.double_features?.length) sections.push(<DoubleFeatures key={key} items={d.double_features} scope={scope} />);
    else if (key === "@spotlights" && d?.spotlights?.length) sections.push(<Spotlights key={key} items={d.spotlights} scope={scope} />);
    else if (byKey[key]) sections.push(<Shelf key={key} s={byKey[key]} scope={scope}
                                              onHide={key === "for-you" ? id => hideFilm(apiBase, id).catch(() => {}) : undefined} />);
  }
  for (const s of d?.shelves || []) if (!LAYOUT.includes(s.key)) sections.push(<Shelf key={s.key} s={s} scope={scope} />);

  return (
    <div className="page theatre-page" style={{ "--tcolor": t.color }}>
      <PageHeader title={t.name} back={{ to: "/theatres", label: "Theatres" }} tour="theatre"
                  meta={[t.area_label && { icon: "📍", label: shell.multiCity ? `${t.area_label} · ${cityOf(shell.cities, t.city)?.name || t.city}` : t.area_label },
                         { icon: "🎬", label: t.films ? `${t.films} film${t.films === 1 ? "" : "s"} in the next month` : "Nothing scheduled right now" },
                         t.films > 0 && { label: "Browse them →", to: `/browse?theatres=${t.slug}&when=month`, more: true }]} />

      <div className="theatre-info">
        <div className="theatre-where">
          {t.address && <p className="theatre-address">{t.address}</p>}
          <div className="theatre-links">
            <a className="btn btn-sm" href={`https://www.google.com/maps/search/?api=1&query=${query}`} target="_blank" rel="noreferrer">Google Maps ↗</a>
            <a className="btn btn-sm" href={`https://maps.apple.com/?q=${encodeURIComponent(t.name)}&address=${encodeURIComponent(t.address || "")}${hasMap ? `&ll=${t.lat},${t.lon}` : ""}`}
               target="_blank" rel="noreferrer">Apple Maps ↗</a>
            {t.website && <a className="btn btn-sm btn-ghost" href={t.website} target="_blank" rel="noreferrer">Theatre website ↗</a>}
            <Link className="btn btn-sm btn-ghost" to={`/calendar?theatres=${slug}`}>On the calendar →</Link>
          </div>
        </div>
        {hasMap && (
          <figure className="theatre-map">
            <iframe title={`Map: ${t.name}`} loading="lazy" referrerPolicy="no-referrer"
                    src={`https://www.openstreetmap.org/export/embed.html?bbox=${box}&layer=mapnik&marker=${t.lat},${t.lon}`} />
            <figcaption>
              <a href={`https://www.openstreetmap.org/?mlat=${t.lat}&mlon=${t.lon}#map=17/${t.lat}/${t.lon}`} target="_blank" rel="noreferrer">
                Larger map
              </a> · © OpenStreetMap contributors
            </figcaption>
          </figure>
        )}
      </div>

      <TheatreNotes apiBase={apiBase} groupId={groupId} slug={slug} />

      {!d && !disc.error && <Loading context="theatre" />}
      {disc.error && !d && <LoadError what={`what's on at ${t.short_name}`} onRetry={disc.reload} />}
      {sections}

      <section className="shelf">
        <SectionTitle link={all.data?.total > 0 ? { to: `/browse?when=month${scope}`, label: `Browse all ${all.data.total} →` } : null}>
          Playing in the next month
        </SectionTitle>
        <div className="browse-tickets"><TicketChips value={tickets} onChange={setTickets} /></div>
        {/* Announced films have their own shelf above; here only when that's what you asked for. */}
        {!all.data ? (all.error ? <LoadError what="the schedule" onRetry={all.reload} /> : <Loading context="theatre" />)
          : tickets === "soon" ? (all.data.announced?.length
            ? <div className="poster-grid">{all.data.announced.map(a => <AnnouncedCard key={a.movie.id} a={a} />)}</div>
            : <p className="pv-empty">Nothing announced here right now.</p>)
          : !all.data.films?.length ? <p className="pv-empty">{tickets ? "Nothing matches — try All." : "Nothing on the schedule yet — check back soon."}</p>
          : <div className="poster-grid">{all.data.films.map(c => <PosterCard key={c.movie.id} card={c} />)}</div>}
      </section>
    </div>
  );
}

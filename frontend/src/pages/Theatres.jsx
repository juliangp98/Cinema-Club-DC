import { useState, useEffect } from "react";
import { Link, useParams } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import PosterCard from "../ui/PosterCard";
import { groupParam } from "../scope";
import "./DiscoverPage.css";
import "./Theatres.css";

const REGION_ORDER = ["DC", "Maryland", "Virginia"];
const dayLabel = iso => new Date(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

function useJson(url) {
  const [data, setData] = useState(null);
  useEffect(() => {
    let live = true;
    setData(null);
    fetch(url, { credentials: "include" })
      .then(r => (r.ok ? r.json() : { error: r.status }))
      .then(d => live && setData(d))
      .catch(() => live && setData({ error: true }));
    return () => { live = false; };
  }, [url]);
  return data;
}

// Every theatre the site follows (R7a), by area, with how busy each is.
export function TheatresPage({ apiBase }) {
  const list = useJson(`${apiBase}/api/theatres-overview`);
  const regions = {};
  for (const t of Array.isArray(list) ? list : []) (regions[t.region || "Other"] ||= []).push(t);
  const order = [...REGION_ORDER.filter(r => regions[r]), ...Object.keys(regions).filter(r => !REGION_ORDER.includes(r))];
  return (
    <div className="page narrow theatres">
      <PageHeader title="Theatres" subtitle="The DC-area theatres we follow, and what's on at each." />
      {!list && <p className="pv-empty">Loading…</p>}
      {list?.error && <p className="pv-empty">Couldn't load the theatres right now.</p>}
      {order.map(region => (
        <section key={region}>
          <SectionTitle>{region}</SectionTitle>
          <ul className="theatre-list">
            {regions[region].map(t => (
              <li key={t.slug}>
                <Link to={`/theatres/${t.slug}`} className="theatre-row" style={{ "--tcolor": t.color }}>
                  <span className="theatre-row-dot" aria-hidden="true" />
                  <span className="theatre-row-text">
                    <span className="theatre-row-name">{t.name}</span>
                    <span className="theatre-row-sub">{t.address}</span>
                  </span>
                  <span className="theatre-row-count">
                    {t.films ? `${t.films} film${t.films === 1 ? "" : "s"}` : "Nothing scheduled"}
                    {t.next && <small>next {dayLabel(t.next)}</small>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

// One theatre (R7a, public): where it is (with a map), and what's playing —
// its rare screenings, then everything in the next month.
export function TheatrePage({ apiBase, groupId }) {
  const { slug } = useParams();
  const t = useJson(`${apiBase}/api/theatres/${slug}`);
  const base = `${apiBase}/api/discover/browse?${groupParam(groupId)}theatres=${slug}&when=month`;
  const rare = useJson(`${base}&shelf=rare`);
  const all = useJson(`${base}&sort=soonest`);

  if (t?.error) {
    return (
      <div className="page narrow">
        <PageHeader title="Theatre not found" back={{ to: "/theatres", label: "Theatres" }} />
        <p className="pv-empty">We don't follow that theatre (any more). <Link to="/theatres">See all theatres →</Link></p>
      </div>
    );
  }
  if (!t) return <div className="page narrow"><p className="pv-empty">Loading…</p></div>;

  const query = encodeURIComponent(`${t.name}, ${t.address || ""}`);
  const hasMap = t.lat != null && t.lon != null;
  const box = hasMap ? [t.lon - 0.009, t.lat - 0.005, t.lon + 0.009, t.lat + 0.005].map(n => n.toFixed(5)).join(",") : "";
  return (
    <div className="page theatre-page">
      <PageHeader title={t.name} back={{ to: "/theatres", label: "Theatres" }}
                  subtitle={[t.region, t.films ? `${t.films} film${t.films === 1 ? "" : "s"} in the next month` : "Nothing scheduled right now"]
                    .filter(Boolean).join(" · ")} />

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

      {rare?.films?.length > 0 && (
        <section className="shelf">
          <SectionTitle action={<Link className="shelf-all" to={`/browse?theatres=${slug}&shelf=rare&when=month`}>See all {rare.total} →</Link>}>
            Rare at {t.short_name}
          </SectionTitle>
          <p className="shelf-blurb">One-offs, film prints, old favorites and special events in the next month.</p>
          <div className="shelf-row">{rare.films.map(c => <PosterCard key={c.movie.id} card={c} />)}</div>
        </section>
      )}

      <section className="shelf">
        <SectionTitle action={all?.total > 0 && <Link className="shelf-all" to={`/browse?theatres=${slug}&when=month`}>Browse all {all.total} →</Link>}>
          Playing in the next month
        </SectionTitle>
        {!all ? <p className="pv-empty">Loading…</p> : !all.films?.length
          ? <p className="pv-empty">Nothing on the schedule yet — check back soon.</p>
          : <div className="poster-grid">{all.films.map(c => <PosterCard key={c.movie.id} card={c} />)}</div>}
      </section>
    </div>
  );
}

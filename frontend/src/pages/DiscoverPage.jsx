import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import PosterCard from "../ui/PosterCard";
import SearchBox from "../ui/SearchBox";
import "./DiscoverPage.css";

const SURPRISE_WHEN = [["tonight", "Tonight"], ["weekend", "This weekend"], ["week", "This week"]];
const FEATURED = 8;   // shelves shown as rows; the rest become "more ways to browse" chips

const timeLabel = iso => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const dayLabel = iso => new Date(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

function Surprise({ apiBase, groupId }) {
  const [when, setWhen] = useState("tonight");
  const [pick, setPick] = useState(null);
  const [seen, setSeen] = useState([]);
  const [state, setState] = useState("idle");   // idle | loading | empty

  async function spin(nextWhen = when, exclude = seen) {
    setState("loading");
    const qs = new URLSearchParams({ group_id: groupId, when: nextWhen, exclude: exclude.join(",") });
    const r = await fetch(`${apiBase}/api/discover/surprise?${qs}`, { credentials: "include" }).catch(() => null);
    if (r?.ok) {
      const p = await r.json();
      setPick(p);
      setSeen([...exclude, p.movie.id]);
      setState("idle");
    } else {
      setPick(null);
      setState("empty");
    }
  }

  return (
    <section className="surprise">
      <div className="surprise-head">
        <span className="deco surprise-title">Surprise me</span>
        <div className="surprise-when" role="group" aria-label="When">
          {SURPRISE_WHEN.map(([k, label]) => (
            <button key={k} type="button" className={`chip${when === k ? " gold" : ""}`}
                    onClick={() => { setWhen(k); setSeen([]); if (pick) spin(k, []); }}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {pick ? (
        <div className="surprise-pick">
          <Link to={`/films/${pick.movie.id}`} className="surprise-poster">
            {pick.movie.poster_url ? <img src={pick.movie.poster_url} alt="" /> : <span>{pick.movie.title}</span>}
          </Link>
          <div className="surprise-text">
            <Link to={`/films/${pick.movie.id}`} className="surprise-film">
              {pick.movie.title}{pick.movie.year ? ` (${pick.movie.year})` : ""}
            </Link>
            <div className="surprise-next">
              {dayLabel(pick.next.start_time)} · {timeLabel(pick.next.start_time)} · {pick.next.theatre}
              {pick.next.format_label ? ` · ${pick.next.format_label}` : ""}
            </div>
            {pick.when !== when && <div className="surprise-note">Nothing left {when === "tonight" ? "tonight" : "then"} — here's one this week.</div>}
            {pick.reasons.length > 0 && (
              <div className="surprise-reasons">{pick.reasons.map(r => <span key={r} className="chip gold">{r}</span>)}</div>
            )}
            <div className="surprise-actions">
              <Link className="btn btn-primary btn-sm" to={`/films/${pick.movie.id}`}>See showings</Link>
              <button className="btn btn-sm" onClick={() => spin()} disabled={state === "loading"}>🎲 Spin again</button>
            </div>
          </div>
        </div>
      ) : (
        <div className="surprise-empty">
          <p>{state === "empty" ? "Nothing left to suggest for then — try a wider window." : "Can't decide? Let the projector pick."}</p>
          <button className="btn btn-primary" onClick={() => spin()} disabled={state === "loading"}>
            🎲 {state === "loading" ? "Picking…" : "Pick a film"}
          </button>
        </div>
      )}
    </section>
  );
}

export default function DiscoverPage({ apiBase, groupId }) {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);

  const load = useCallback(() => {
    fetch(`${apiBase}/api/discover?group_id=${groupId}`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(setData)
      .catch(() => setError(true));
  }, [apiBase, groupId]);
  useEffect(() => { setData(null); load(); }, [load]);

  const featured = data?.shelves.slice(0, FEATURED) || [];
  const more = data?.shelves.slice(FEATURED) || [];

  return (
    <div className="page discover">
      <PageHeader title="Discover" subtitle="What's playing across the club's theatres in the next two weeks." />
      <SearchBox onSearch={q => navigate(`/browse?q=${encodeURIComponent(q)}&when=month`)} />

      <div className="discover-top">
        <Surprise apiBase={apiBase} groupId={groupId} />
        <section className="moods">
          <span className="deco moods-title">In the mood for…</span>
          <div className="moods-chips">
            {(data?.moods || []).map(m => (
              <Link key={m.key} className="mood-chip" to={`/browse?mood=${m.key}&when=2weeks`}>{m.label}</Link>
            ))}
          </div>
        </section>
      </div>

      {error && <p className="discover-empty">Couldn't load Discover right now.</p>}
      {!data && !error && <p className="discover-empty">Loading…</p>}

      {featured.map(s => (
        <section key={s.key} className="shelf">
          <SectionTitle action={<Link className="shelf-all" to={`/browse?shelf=${s.key}&when=2weeks`}>See all {s.total} →</Link>}>
            {s.title}
          </SectionTitle>
          <p className="shelf-blurb">{s.blurb}</p>
          <div className="shelf-row">
            {s.items.map(c => <PosterCard key={c.movie.id} card={c} />)}
          </div>
        </section>
      ))}

      {data?.double_features.length > 0 && (
        <section className="shelf">
          <SectionTitle>Double features</SectionTitle>
          <p className="shelf-blurb">Two films, one theatre, one evening — with time for a drink in between.</p>
          <div className="doubles">
            {data.double_features.slice(0, 6).map((d, i) => (
              <div key={i} className="double">
                {[d.first, d.second].map((c, j) => (
                  <Link key={j} to={`/films/${c.movie.id}`} className="double-film">
                    {c.movie.poster_url && <img src={c.movie.poster_url} alt="" loading="lazy" />}
                    <span className="double-time">{timeLabel(c.next.start_time)}</span>
                    <span className="double-title">{c.movie.title}</span>
                  </Link>
                ))}
                <div className="double-meta">{d.theatre} · {dayLabel(d.first.next.start_time)} · {d.gap_minutes}-min break</div>
              </div>
            ))}
          </div>
        </section>
      )}

      {data?.spotlights.length > 0 && (
        <section className="shelf">
          <SectionTitle>Spotlights</SectionTitle>
          <p className="shelf-blurb">Directors and stars with several films playing this month.</p>
          <div className="spotlights">
            {data.spotlights.map(sp => (
              <Link key={sp.name} className="spotlight" to={`/browse?q=${encodeURIComponent(sp.name)}&when=month`}>
                <div className="spotlight-head">
                  <span className="spotlight-name">{sp.name}</span>
                  <span className="spotlight-count">{sp.count} films · {sp.role}</span>
                </div>
                <div className="spotlight-posters">
                  {sp.films.slice(0, 4).map(f => f.movie.poster_url
                    ? <img key={f.movie.id} src={f.movie.poster_url} alt={f.movie.title} loading="lazy" />
                    : <span key={f.movie.id} className="spotlight-ph">{f.movie.title}</span>)}
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {more.length > 0 && (
        <section className="shelf">
          <SectionTitle>More ways to browse</SectionTitle>
          <div className="moods-chips">
            {more.map(s => (
              <Link key={s.key} className="mood-chip" to={`/browse?shelf=${s.key}&when=2weeks`}>
                {s.title} <span className="mood-count">{s.total}</span>
              </Link>
            ))}
            <Link className="mood-chip" to="/browse?when=week">Everything this week →</Link>
          </div>
        </section>
      )}
    </div>
  );
}

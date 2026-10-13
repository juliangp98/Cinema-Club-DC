import { useEffect, useState } from "react";
import { getJson, send } from "../api";
import { SheetTitle } from "../ui/Sheet";
import { Segmented } from "../ui/TicketRow";
import ToggleChip, { RemovableChip } from "../ui/ToggleChip";
import PickSearch from "../ui/PickSearch";
import { PEOPLE_KINDS, PERSON_KIND } from "../ui/TasteChips";

// Your taste (R13): what For you, Discover and /foryou go on — genres you love
// or aren't into, how you like to watch, favorite theatres, films and people.
// Saved as you go. Shown to others only if you switch that on.
export default function TasteEditor({ apiBase }) {
  const [t, setT] = useState(null);
  const [error, setError] = useState(null);
  const [kind, setKind] = useState("director");
  useEffect(() => {
    getJson(`${apiBase}/api/me/taste`, { cache: false }).then(setT)
      .catch(() => setError("Couldn't load your taste — try again in a bit."));
  }, [apiBase]);

  async function save(method, path, body) {
    setError(null);
    try { setT(await send(`${apiBase}/api/me/taste${path}`, method, body)); } catch (e) { setError(e.message); }
  }
  if (!t) return <div className="taste-editor"><SheetTitle>Your taste</SheetTitle>{error && <p className="ui-hint">{error}</p>}</div>;

  const flip = (list, k) => (list.includes(k) ? list.filter(x => x !== k) : [...list, k]);
  const love = k => save("PUT", "", { genres: flip(t.genres, k) });
  const avoid = k => save("PUT", "", t.genres.includes(k) ? { genres: t.genres.filter(x => x !== k), avoid: [...t.avoid, k] }
                                                           : { avoid: flip(t.avoid, k) });
  const findFilms = async (q, signal) => {
    const opts = { signal, retries: 0, cache: false };
    const [ours, tmdb] = await Promise.all([
      getJson(`${apiBase}/api/search/suggest?${new URLSearchParams({ q })}`, opts).catch(() => null),
      getJson(`${apiBase}/api/films/tmdb-search?${new URLSearchParams({ q })}`, opts).catch(() => null),
    ]);
    const mine = (ours?.films || []).map(f => ({ key: `m${f.id}`, label: f.title, sub: f.year, pick: { movie_id: f.id } }));
    const have = new Set(mine.map(f => f.pick.movie_id));
    return [...mine, ...(tmdb?.results || []).filter(f => !have.has(f.movie_id))
      .map(f => ({ key: `t${f.tmdb_id}`, label: f.title, sub: f.year, pick: f.movie_id ? { movie_id: f.movie_id } : { tmdb_id: f.tmdb_id } }))]
      .slice(0, 8);
  };
  const findPeople = async (q, signal) => (await getJson(`${apiBase}/api/taste/people?${new URLSearchParams({ q, kind })}`,
    { signal, retries: 0, cache: false })).map(p => ({ key: `${p.kind}:${p.name}`, label: p.name, sub: PERSON_KIND[p.kind], pick: p }));

  return (
    <div className="taste-editor">
      <SheetTitle>Your taste</SheetTitle>
      <p className="ui-hint">What we go on for For you on Discover and theatre pages (and /foryou in Discord). Saved as you go.</p>
      {error && <p className="share-error" role="alert">{error}</p>}

      <section aria-labelledby="taste-love">
        <div className="profile-section-label" id="taste-love">Genres you love</div>
        <div className="filter-chips">{t.options.genres.map(g => (
          <ToggleChip key={g.key} on={t.genres.includes(g.key)} onClick={() => love(g.key)}>{g.label}</ToggleChip>))}</div>
      </section>
      <section aria-labelledby="taste-avoid">
        <div className="profile-section-label" id="taste-avoid">Not into</div>
        <div className="filter-chips">{t.options.genres.map(g => (
          <ToggleChip key={g.key} on={t.avoid.includes(g.key)} onClick={() => avoid(g.key)}>{g.label}</ToggleChip>))}</div>
      </section>
      <section aria-labelledby="taste-ways">
        <div className="profile-section-label" id="taste-ways">How you like to watch</div>
        <div className="filter-chips">{t.options.ways.map(w => (
          <ToggleChip key={w.key} on={t.ways.includes(w.key)} onClick={() => save("PUT", "", { ways: flip(t.ways, w.key) })}>
            {w.emoji} {w.label}</ToggleChip>))}</div>
      </section>
      <section aria-labelledby="taste-theatres">
        <div className="profile-section-label" id="taste-theatres">Favorite theatres</div>
        <div className="filter-chips">{t.options.theatres.map(th => (
          <ToggleChip key={th.slug} color={th.color} on={t.theatres.includes(th.slug)}
                      onClick={() => save("PUT", "", { theatres: flip(t.theatres, th.slug) })}>{th.short_name}</ToggleChip>))}</div>
      </section>
      <section aria-labelledby="taste-films">
        <div className="profile-section-label" id="taste-films">Favorite films</div>
        {t.movies.length > 0 && <div className="filter-chips">{t.movies.map(m => (
          <RemovableChip key={m.key} label={m.label} onRemove={() => save("DELETE", "/items", { kind: "movie", key: m.key })}>
            {m.label}{m.year ? ` (${m.year})` : ""}</RemovableChip>))}</div>}
        <PickSearch label="Add a favorite film" placeholder="Any film…" search={findFilms}
                    onPick={r => save("POST", "/items", { kind: "movie", ...r.pick })} />
      </section>
      <section aria-labelledby="taste-people">
        <div className="profile-section-label" id="taste-people">Favorite people</div>
        {t.people.length > 0 && <div className="filter-chips">{t.people.map(p => (
          <RemovableChip key={`${p.kind}${p.key}`} label={p.label} onRemove={() => save("DELETE", "/items", { kind: p.kind, key: p.key })}>
            {p.label} · {PERSON_KIND[p.kind]}</RemovableChip>))}</div>}
        <Segmented label="Who" options={PEOPLE_KINDS} value={kind} onChange={v => v && setKind(v)} />
        <PickSearch label={`Add a favorite ${PERSON_KIND[kind]}`} placeholder="A name…" search={findPeople} deps={[kind]}
                    onPick={r => save("POST", "/items", { kind: r.pick.kind, name: r.pick.name })} />
      </section>
      {t.hidden.length > 0 && (
        <section aria-labelledby="taste-hidden">
          <div className="profile-section-label" id="taste-hidden">Not for me</div>
          <div className="filter-chips">{t.hidden.map(m => (
            <RemovableChip key={m.key} label={m.label} onRemove={() => save("DELETE", "/items", { kind: "hide", key: m.key })}>
              {m.label}</RemovableChip>))}</div>
        </section>
      )}
      <label className="notify-row taste-public">
        <input type="checkbox" checked={t.public} onChange={e => save("PUT", "", { public: e.target.checked })} />
        <span><span className="notify-name">Show my taste on my profile</span>
          <span className="ui-hint"> People in your clubs see it on your profile and in Discord. Off: only you see it.</span></span>
      </label>
    </div>
  );
}

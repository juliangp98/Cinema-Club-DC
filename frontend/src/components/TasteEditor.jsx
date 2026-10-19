import { useEffect, useState } from "react";
import { getJson, send } from "../api";
import { Segmented } from "../ui/TicketRow";
import ToggleChip, { RemovableChip } from "../ui/ToggleChip";
import PickSearch from "../ui/PickSearch";
import TheatrePicker from "../ui/TheatrePicker";
import { useShell } from "../shell/AppShell";
import { DEFAULT_CITY } from "../places";
import { PEOPLE_KINDS, PERSON_KIND } from "../ui/TasteChips";

// Your taste (R13): what For you, Discover and /foryou go on — genres you love
// or aren't into, how you like to watch, favorite theatres, films and people.
// Saved as you go. Shown to others only if you switch that on (Settings →
// Privacy and sharing). Lives in Me → Settings (7g); `onChange` hears each save.
export default function TasteEditor({ apiBase, onChange }) {
  const shell = useShell();
  const [t, setT] = useState(null);
  const [error, setError] = useState(null);
  const [kind, setKind] = useState("director");
  useEffect(() => {
    getJson(`${apiBase}/api/me/taste`, { cache: false }).then(setT)
      .catch(() => setError("Couldn't load your taste — try again in a bit."));
  }, [apiBase]);

  async function save(method, path, body) {
    setError(null);
    try {
      const next = await send(`${apiBase}/api/me/taste${path}`, method, body);
      setT(next);
      onChange?.(next);
    } catch (e) { setError(e.message); }
  }
  if (!t) return <div className="taste-editor">{error && <p className="ui-hint">{error}</p>}</div>;

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
      {error && <p className="share-error" role="alert">{error}</p>}

      <section aria-labelledby="taste-love">
        <h3 className="ui-settings-group-title" id="taste-love">Genres you love</h3>
        <div className="filter-chips">{t.options.genres.map(g => (
          <ToggleChip key={g.key} on={t.genres.includes(g.key)} onClick={() => love(g.key)}>{g.label}</ToggleChip>))}</div>
      </section>
      <section aria-labelledby="taste-avoid">
        <h3 className="ui-settings-group-title" id="taste-avoid">Not into</h3>
        <div className="filter-chips">{t.options.genres.map(g => (
          <ToggleChip key={g.key} on={t.avoid.includes(g.key)} onClick={() => avoid(g.key)}>{g.label}</ToggleChip>))}</div>
      </section>
      <section aria-labelledby="taste-ways">
        <h3 className="ui-settings-group-title" id="taste-ways">How you like to watch</h3>
        <div className="filter-chips">{t.options.ways.map(w => (
          <ToggleChip key={w.key} on={t.ways.includes(w.key)} onClick={() => save("PUT", "", { ways: flip(t.ways, w.key) })}>
            {w.emoji} {w.label}</ToggleChip>))}</div>
      </section>
      <section aria-labelledby="taste-theatres">
        <h3 className="ui-settings-group-title" id="taste-theatres">Favorite theatres</h3>
        <TheatrePicker theatres={t.options.theatres} home={shell?.city || DEFAULT_CITY} cities={shell?.cities || []}
                       label="Favorite theatres" isOn={slug => t.theatres.includes(slug)}
                       onToggle={slug => save("PUT", "", { theatres: flip(t.theatres, slug) })} />
      </section>
      <section aria-labelledby="taste-films">
        <h3 className="ui-settings-group-title" id="taste-films">Favorite films</h3>
        {t.movies.length > 0 && <div className="filter-chips">{t.movies.map(m => (
          <RemovableChip key={m.key} label={m.label} onRemove={() => save("DELETE", "/items", { kind: "movie", key: m.key })}>
            {m.label}{m.year ? ` (${m.year})` : ""}</RemovableChip>))}</div>}
        <PickSearch label="Add a favorite film" placeholder="Any film…" search={findFilms}
                    onPick={r => save("POST", "/items", { kind: "movie", ...r.pick })} />
      </section>
      <section aria-labelledby="taste-people">
        <h3 className="ui-settings-group-title" id="taste-people">Favorite people</h3>
        {t.people.length > 0 && <div className="filter-chips">{t.people.map(p => (
          <RemovableChip key={`${p.kind}${p.key}`} label={p.label} onRemove={() => save("DELETE", "/items", { kind: p.kind, key: p.key })}>
            {p.label} · {PERSON_KIND[p.kind]}</RemovableChip>))}</div>}
        <Segmented label="Who" options={PEOPLE_KINDS} value={kind} onChange={v => v && setKind(v)} />
        <PickSearch label={`Add a favorite ${PERSON_KIND[kind]}`} placeholder="A name…" search={findPeople} deps={[kind]}
                    onPick={r => save("POST", "/items", { kind: r.pick.kind, name: r.pick.name })} />
      </section>
      {t.hidden.length > 0 && (
        <section aria-labelledby="taste-hidden">
          <h3 className="ui-settings-group-title" id="taste-hidden">Not for me</h3>
          <div className="filter-chips">{t.hidden.map(m => (
            <RemovableChip key={m.key} label={m.label} onRemove={() => save("DELETE", "/items", { kind: "hide", key: m.key })}>
              {m.label}</RemovableChip>))}</div>
        </section>
      )}
    </div>
  );
}

import { useState, useEffect, useRef, useId } from "react";
import { useNavigate } from "react-router-dom";
import { getJson, send } from "../api";
import { useShell } from "../shell/AppShell";
import Poster from "./Poster";
import SearchField, { SearchAction } from "./SearchField";
import { dayDate } from "../dates";

const GROUPS = [["films", "Films"], ["people", "People"], ["filters", "Filters"]];
const ROLE = { director: "Director", actor: "Actor" };
const yearOf = f => (f.year ? ` (${f.year})` : "");
const nextLabel = dayDate;

// Default for picks outside Browse: open Browse with them (a month ahead).
export const browseUrl = params => `/browse?${new URLSearchParams({ when: "month", ...params })}`;

// The search box (R6c). As you type it suggests films (playing first, then
// the rest of the database), directors and actors, and Browse filters; Enter
// searches the text. ✨ (kept accounts only) reads a plain-English request
// with the AI and turns it into filters.
//   onSearch(text)            plain search
//   onApply(params, {replace, note})  a picked person / filter, or the AI's filters
// Without onApply, picks open Browse.
export default function SearchBox({ initial = "", onSearch, onApply, apiBase = "", groupId, autoFocus, ai = true, showNote = true,
                                    placeholder = "Search films, people, genres, moods…" }) {
  const shell = useShell();
  const navigate = useNavigate();
  const [q, setQ] = useState(initial);
  const [results, setResults] = useState(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [thinking, setThinking] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const listId = useId();
  const typed = useRef(false);            // only suggest after the person types (not for `initial`)
  const user = shell?.user;
  const canAi = ai && user && !user.is_guest && !!shell?.groupId;          // ✨ is for club members (it spends the club's AI allowance)

  useEffect(() => setQ(initial), [initial]);

  useEffect(() => {
    const text = q.trim();
    if (!typed.current || text.length < 2) { setResults(null); return undefined; }
    const ctl = new AbortController();
    const timer = setTimeout(() => {
      const qs = new URLSearchParams({ q: text, ...(groupId ? { group_id: groupId } : {}) });
      getJson(`${apiBase}/api/search/suggest?${qs}`, { signal: ctl.signal, retries: 0, cache: false })
        .then(d => { if (d) { setResults(d); setActive(-1); setOpen(true); } })
        .catch(() => {});
    }, 140);
    return () => { clearTimeout(timer); ctl.abort(); };
  }, [q, apiBase, groupId]);

  // Any film on TMDB (R8c), for signed-in people: films no theatre we follow has
  // listed, to open and watchlist. A little slower to ask, so it waits longer.
  const [tmdb, setTmdb] = useState([]);
  useEffect(() => {
    const text = q.trim();
    if (!user || !typed.current || text.length < 3) { setTmdb([]); return undefined; }
    const ctl = new AbortController();
    const timer = setTimeout(() => {
      getJson(`${apiBase}/api/films/tmdb-search?${new URLSearchParams({ q: text })}`, { signal: ctl.signal, retries: 0, cache: false })
        .then(d => { if (d) { setTmdb(d.results || []); setOpen(true); } })
        .catch(() => {});
    }, 450);
    return () => { clearTimeout(timer); ctl.abort(); };
  }, [q, apiBase, user]);

  // Groups in the order the server ranks them (best match first), then TMDB's.
  const ours = new Set((results?.films || []).map(f => f.id));
  const lists = { ...(results || { films: [], people: [], filters: [] }),
                  tmdb: tmdb.filter(t => !ours.has(t.movie_id)).slice(0, 5) };
  const groups = [...(results ? (results.order || GROUPS.map(([k]) => k)).map(k => GROUPS.find(([g]) => g === k)) : []),
                  ...(lists.tmdb.length ? [["tmdb", "More films"]] : [])];
  const items = groups.flatMap(([key]) => lists[key].map(x => ({ kind: key, x })));
  const showList = open && items.length > 0;

  const apply = (params, extra = {}) => {
    if (onApply) onApply(params, extra);
    else navigate(browseUrl(params), { state: extra.note ? { searchNote: extra.note } : undefined });
  };
  function pick(item) {
    setOpen(false);
    typed.current = false;
    if (item.kind === "films") { navigate(`/films/${item.x.id}`); return; }
    if (item.kind === "tmdb") { openTmdb(item.x); return; }
    if (item.kind === "people") setQ(item.x.name);
    else setQ("");
    setNote("");
    apply(item.x.params);
  }
  function submit(e) {
    e.preventDefault();
    if (showList && active >= 0) { pick(items[active]); return; }
    setOpen(false);
    setNote("");
    onSearch?.(q.trim());
  }
  function onKey(e) {
    if (e.key === "ArrowDown" && items.length) { e.preventDefault(); setOpen(true); setActive(a => (a + 1) % items.length); }
    else if (e.key === "ArrowUp" && items.length) { e.preventDefault(); setActive(a => (a <= 0 ? items.length - 1 : a - 1)); }
    else if (e.key === "Escape" && showList) { e.preventDefault(); e.stopPropagation(); setOpen(false); }
  }
  async function askAi() {
    if (q.trim().length < 3 || thinking) return;
    setThinking(true);
    setError("");
    setOpen(false);
    let d;
    try {
      d = await send(`${apiBase}/api/search/ai`, "POST", { q: q.trim(), ...(groupId ? { group_id: groupId } : {}) });
    } catch (e) {
      setError(e.data?.error || "Couldn't reach the AI — try again.");
      return;
    } finally { setThinking(false); }
    const text = `${d.ai ? "✨ " : ""}Showing: ${d.explain}${d.note ? ` — ${d.note}` : ""}`;
    typed.current = false;
    setNote(text);
    apply(d.params, { replace: true, note: text });
  }

  async function openTmdb(t) {
    if (t.movie_id) { navigate(`/films/${t.movie_id}`); return; }
    send(`${apiBase}/api/films/from-tmdb`, "POST", { tmdb_id: t.tmdb_id })
      .then(d => navigate(`/films/${d.movie_id}`))
      .catch(() => setError("Couldn't open that film — try again in a bit."));
  }

  let i = -1;
  return (
    <div className="searchbox-wrap">
      <SearchField value={q} label="Search films" placeholder={canAi ? "Search, or describe what you want and tap ✨" : placeholder}
                   onSubmit={submit} onChange={v => { typed.current = true; setQ(v); setError(""); }}
                   onClear={() => { setQ(""); setResults(null); setNote(""); typed.current = false; onSearch?.(""); }}
                   inputProps={{
                     autoFocus, spellCheck: "false", role: "combobox", "aria-expanded": showList, "aria-controls": listId,
                     "aria-autocomplete": "list", "aria-activedescendant": showList && active >= 0 ? `${listId}-${active}` : undefined,
                     onKeyDown: onKey, onFocus: () => results && setOpen(true), onBlur: () => setTimeout(() => setOpen(false), 120),
                   }}
                   action={canAi && (
                     <SearchAction busy={thinking} onClick={askAi} disabled={thinking || q.trim().length < 3}
                                   title="AI search: describe what you're in the mood for" aria-label="AI search">
                       {thinking ? "…" : "✨"}
                     </SearchAction>
                   )} />
      {showList && (
        <div className="searchbox-list" id={listId} role="listbox" aria-label="Suggestions">
          {groups.map(([key, title]) => lists[key].length > 0 && (
            <div key={key} role="group" aria-label={title}>
              <div className="searchbox-group">{title}</div>
              {lists[key].map(x => {
                i += 1;
                const n = i;
                const item = { kind: key, x };
                return (
                  <div key={`${key}-${x.id || x.tmdb_id || x.name || x.label}`} id={`${listId}-${n}`} role="option" aria-selected={active === n}
                       className={`searchbox-option${active === n ? " active" : ""}`}
                       onMouseDown={e => e.preventDefault()} onMouseEnter={() => setActive(n)} onClick={() => pick(item)}>
                    {(key === "films" || key === "tmdb") && <Poster movie={x} className="searchbox-poster" />}
                    <span className="searchbox-option-text">
                      <span className="searchbox-option-label">
                        {key === "films" || key === "tmdb" ? `${x.title}${yearOf(x)}` : key === "people" ? x.name : x.label}
                      </span>
                      <span className="searchbox-option-hint">
                        {key === "films" ? (x.playing ? `Next: ${nextLabel(x.next)} · ${x.theatre}` : "Not playing right now")
                          : key === "tmdb" ? (x.movie_id ? "Not playing right now" : "Not listed here yet — open it to watchlist")
                          : key === "people" ? `${ROLE[x.role] || "Person"} · ${x.count} film${x.count === 1 ? "" : "s"} playing`
                          : x.hint}
                      </span>
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
          {canAi && q.trim().length >= 3 && (
            <button type="button" className="searchbox-ai-row" onMouseDown={e => e.preventDefault()} onClick={askAi}>
              ✨ Ask the AI: “{q.trim()}”
            </button>
          )}
        </div>
      )}
      {((showNote && note) || error) && <p className={error ? "share-error searchbox-note" : "searchbox-note"} role="status">{error || note}</p>}
    </div>
  );
}

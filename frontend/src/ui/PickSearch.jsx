import { useEffect, useState } from "react";

// Type to search, tap a result to pick it (R13): favorite films and people.
// `search(text, signal)` resolves to [{key, label, sub?}]; it's asked from two
// letters on, a moment after typing stops. `deps` re-ask when they change.
export default function PickSearch({ label, placeholder, search, onPick, deps = [] }) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  useEffect(() => {
    const text = q.trim();
    if (text.length < 2) { setResults([]); return undefined; }
    const ctl = new AbortController();
    const t = setTimeout(() => search(text, ctl.signal).then(r => { if (!ctl.signal.aborted) setResults(r); }).catch(() => {}), 250);
    return () => { clearTimeout(t); ctl.abort(); };
  }, [q, ...deps]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="pick-search">
      <input type="search" className="share-input" aria-label={label} placeholder={placeholder} value={q}
             onChange={e => setQ(e.target.value)} />
      {results.length > 0 && (
        <ul className="pick-results" aria-label={`${label}: results`}>
          {results.map(r => (
            <li key={r.key}>
              <button type="button" className="pick-result" onClick={() => { onPick(r); setQ(""); setResults([]); }}>
                <span>{r.label}</span>{r.sub && <span className="ui-hint">{r.sub}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

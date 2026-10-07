import { useState, useEffect } from "react";

// Film search: title, director or cast. Calls onSearch with the trimmed text.
export default function SearchBox({ initial = "", onSearch, placeholder = "Search films, directors, actors…", autoFocus }) {
  const [q, setQ] = useState(initial);
  useEffect(() => setQ(initial), [initial]);
  return (
    <form className="searchbox" role="search" onSubmit={e => { e.preventDefault(); onSearch(q.trim()); }}>
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
      </svg>
      <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder={placeholder}
             aria-label="Search films" autoFocus={autoFocus} />
      {q && <button type="button" className="searchbox-clear" aria-label="Clear" onClick={() => { setQ(""); onSearch(""); }}>&times;</button>}
    </form>
  );
}

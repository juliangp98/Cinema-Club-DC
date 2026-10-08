import { useState, useEffect } from "react";

const webcal = url => url.replace(/^https?:\/\//, "webcal://");
const google = url => `https://calendar.google.com/calendar/r?cid=${encodeURIComponent(webcal(url))}`;

// Subscribe in a calendar app (R7a): your Going + Maybe plans, and each of your
// clubs' plans. Calendar apps re-check the link (about hourly), so new plans
// appear and changed ones update. `clubId` shows just that club's link.
export default function CalendarLinks({ apiBase, clubId }) {
  const [links, setLinks] = useState(null);
  const [copied, setCopied] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    fetch(`${apiBase}/api/me/calendar`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(setLinks)
      .catch(() => setLinks(null));
  }, [apiBase]);
  if (!links) return null;

  async function copy(url, key) {
    try { await navigator.clipboard.writeText(url); setCopied(key); setTimeout(() => setCopied(""), 2000); }
    catch { window.prompt("Copy this link:", url); }
  }
  async function reset(groupId) {
    if (!window.confirm("Make a new link? Calendars subscribed to the old one stop updating; you'll need to subscribe again.")) return;
    setError("");
    const r = await fetch(`${apiBase}/api/me/calendar/reset`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(groupId ? { group_id: groupId } : {}),
    }).catch(() => null);
    if (r?.ok) setLinks(await r.json()); else setError("Couldn't make a new link — try again.");
  }

  const rows = clubId
    ? links.clubs.filter(c => c.group_id === clubId).map(c => ({ key: `c${c.group_id}`, title: "Club plans", hint:
        "Every screening members are going to (or maybe going to), with who's going.", url: c.url, groupId: c.group_id }))
    : [{ key: "me", title: "My plans", hint: "Screenings you're going to, and ones you marked Maybe.", url: links.personal },
       ...links.clubs.map(c => ({ key: `c${c.group_id}`, title: `${c.name}'s plans`, hint: "What the club is going to, with who's going.",
                                  url: c.url, groupId: c.group_id }))];
  return (
    <div className="cal-links">
      {rows.map(row => (
        <div key={row.key} className="cal-link">
          <div className="cal-link-text">
            <span className="cal-link-title">{row.title}</span>
            <span className="cal-link-hint">{row.hint}</span>
          </div>
          <div className="cal-link-actions">
            <a className="btn btn-sm btn-primary" href={google(row.url)} target="_blank" rel="noreferrer">Google Calendar</a>
            <a className="btn btn-sm" href={webcal(row.url)}>Apple / Outlook</a>
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => copy(row.url, row.key)}>
              {copied === row.key ? "Copied" : "Copy link"}
            </button>
            <button type="button" className="share-link" onClick={() => reset(row.groupId)}>New link</button>
          </div>
        </div>
      ))}
      <p className="pv-hint">Anyone with a link can see what's on it, so keep it to yourself. "New link" turns the old one off.</p>
      {error && <p className="share-error">{error}</p>}
    </div>
  );
}

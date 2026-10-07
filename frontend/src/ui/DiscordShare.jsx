import { useState, useEffect } from "react";
import Sheet from "./Sheet";

// Choosing what goes to the club's Discord (R3d). Nothing posts to #movies
// unless you share it; shared posts stay in step with the site and never
// @-ping anyone. Only screenings and polls in the Discord server's group
// carry a `discord` block, so everything here hides itself elsewhere.

async function call(apiBase, path, method = "GET", body) {
  const r = await fetch(`${apiBase}${path}`, {
    method, credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  }).catch(() => null);
  const data = r ? await r.json().catch(() => ({})) : {};
  if (!r?.ok) throw new Error(data.error || "Couldn't reach the server — try again.");
  return data;
}

export const shareToDiscord = (apiBase, body) => call(apiBase, "/api/discord/shares", "POST", body);
export const unshareFromDiscord = (apiBase, id, showtimeId) =>
  call(apiBase, `/api/discord/shares/${id}${showtimeId ? `?showtime_id=${showtimeId}` : ""}`, "DELETE");
export const postNow = (apiBase, id) => call(apiBase, `/api/discord/shares/${id}/now`, "POST");
export const setSharePrefs = (apiBase, prefs) => call(apiBase, "/api/discord/prefs", "PUT", prefs);
export const getSharePrefs = apiBase => call(apiBase, "/api/discord/prefs");

const at = iso => new Date(iso).toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
// Scheduled for later (beyond the minute an RSVP waits to batch).
export const isScheduled = p => p?.status === "pending" && new Date(p.post_at) - Date.now() > 2 * 60 * 1000;

// <input type="datetime-local"> value for a Date, in local time.
function localInput(d) {
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// Now, or later at a time you pick. value: { when: "now" | "later" | "none", at }
export function ShareWhen({ value, onChange, allowNone = false, noneLabel = "Not yet" }) {
  const defaultAt = () => {
    const d = new Date(Date.now() + 60 * 60 * 1000);
    d.setMinutes(0, 0, 0);
    return localInput(d);
  };
  const opts = [["now", "Now"], ["later", "Later"], ...(allowNone ? [["none", noneLabel]] : [])];
  return (
    <div className="share-when">
      <div className="seg" role="group" aria-label="When to post">
        {opts.map(([k, label]) => (
          <button key={k} type="button" className={`seg-btn${value.when === k ? " on" : ""}`} aria-pressed={value.when === k}
                  onClick={() => onChange({ when: k, at: k === "later" ? (value.at || defaultAt()) : value.at })}>
            {label}
          </button>
        ))}
      </div>
      {value.when === "later" && (
        <input type="datetime-local" className="share-when-at" value={value.at || ""} min={localInput(new Date())}
               onChange={e => onChange({ ...value, at: e.target.value })} aria-label="Post at" />
      )}
    </div>
  );
}

// "Who's in?": post an invite card for a screening, now or later, with a note.
function InviteSheet({ showtime, apiBase, groupId, onClose, onDone }) {
  const [note, setNote] = useState("");
  const [when, setWhen] = useState({ when: "now" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function send() {
    setBusy(true);
    setError("");
    try {
      onDone(await shareToDiscord(apiBase, {
        kind: "invite", group_id: groupId, showtime_id: showtime.id, note,
        post_at: when.when === "later" ? when.at : undefined,
      }));
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Sheet label="Ask who's in" onClose={onClose} className="share-sheet">
      <div className="share-sheet-body">
        <h2 className="ui-section-title"><span className="deco share-sheet-title">Who's in?</span></h2>
        <p className="share-sheet-lead">
          Posts a card for <strong>{showtime.movie?.title}</strong> in #movies with Going and Maybe buttons. Its list
          stays current as people answer, here or there. Nobody gets pinged.
        </p>
        <label className="share-label" htmlFor="invite-note">Add a note (optional)</label>
        <input id="invite-note" className="share-input" maxLength={200} value={note} placeholder="Drinks after?"
               onChange={e => setNote(e.target.value)} />
        <span className="share-label">When</span>
        <ShareWhen value={when} onChange={setWhen} />
        {error && <p className="share-error">{error}</p>}
        <div className="share-sheet-foot">
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button type="button" className="btn btn-primary" onClick={send} disabled={busy || (when.when === "later" && !when.at)}>
            {busy ? "Posting…" : when.when === "later" ? "Schedule" : "Post in #movies"}
          </button>
        </div>
      </div>
    </Sheet>
  );
}

// A post's state, compactly: "Posting shortly", "Scheduled for …", "In #movies ↗".
function PostState({ post, label }) {
  if (post.status === "posted") {
    return post.jump_url
      ? <a className="share-state" href={post.jump_url} target="_blank" rel="noreferrer">{label} in #movies ↗</a>
      : <span className="share-state">{label} in #movies</span>;
  }
  return <span className="share-state">{isScheduled(post) ? `${label} · scheduled for ${at(post.post_at)}` : `${label} · posting shortly`}</span>;
}

// Under a ticket's RSVP: the "share in #movies?" prompt, your share's state,
// and "Who's in?". `discord` comes with the screening (null = not the Discord group).
export function TicketDiscord({ showtime: s, apiBase, groupId }) {
  const [d, setD] = useState(s.discord);
  const [inviting, setInviting] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setD(s.discord); setError(""); }, [s.discord]);
  if (!d || !groupId) return null;

  const rsvpd = s.user_rsvp === "going" || s.user_rsvp === "maybe";
  const run = async (fn) => {
    setError("");
    try { await fn(); } catch (e) { setError(e.message); }
  };
  const share = (remember = false) => run(async () => {
    const post = await shareToDiscord(apiBase, { kind: "rsvp", group_id: groupId, showtime_id: s.id, remember });
    setD(prev => ({ ...prev, prompt: false, my_share: post }));
  });
  const notNow = (remember = false) => run(async () => {
    if (remember) await setSharePrefs(apiBase, { rsvp: "never" });
    setD(prev => ({ ...prev, prompt: false }));
  });
  const undo = () => run(async () => {
    await unshareFromDiscord(apiBase, d.my_share.id, s.id);
    setD(prev => ({ ...prev, my_share: null }));
  });
  const invite = d.invite;

  return (
    <div className="ticket-discord">
      {d.prompt && rsvpd && !d.my_share ? (
        <div className="share-prompt" role="group" aria-label="Share in Discord">
          <span>Share in #movies?</span>
          <button type="button" className="btn btn-sm btn-primary" onClick={() => share(false)}>Share</button>
          <button type="button" className="btn btn-sm" onClick={() => notNow(false)}>Not now</button>
          <span className="share-remember">
            <button type="button" className="share-link" onClick={() => share(true)}>Always share</button>
            {" · "}
            <button type="button" className="share-link" onClick={() => notNow(true)}>Never ask</button>
          </span>
        </div>
      ) : d.my_share ? (
        <div className="share-row">
          <PostState post={d.my_share} label="Your RSVP" />
          <button type="button" className="share-link" onClick={undo}>{d.my_share.status === "posted" ? "Remove" : "Undo"}</button>
        </div>
      ) : rsvpd ? (
        <div className="share-row">
          <button type="button" className="share-link" onClick={() => share(false)}>Share your RSVP in #movies</button>
        </div>
      ) : null}

      <div className="share-row">
        {invite ? (
          <>
            <PostState post={invite} label={`${invite.by.name}'s “Who's in?”`} />
            {invite.status === "pending" && isScheduled(invite) && (
              <button type="button" className="share-link"
                      onClick={() => run(async () => { const p = await postNow(apiBase, invite.id); setD(prev => ({ ...prev, invite: p })); })}>
                Post now
              </button>
            )}
            <button type="button" className="share-link"
                    onClick={() => run(async () => { await unshareFromDiscord(apiBase, invite.id); setD(prev => ({ ...prev, invite: null })); })}>
              {invite.status === "posted" ? "Remove" : "Cancel"}
            </button>
          </>
        ) : (
          <button type="button" className="share-link" onClick={() => setInviting(true)}>Ask who's in on Discord…</button>
        )}
      </div>
      {error && <p className="share-error">{error}</p>}
      {inviting && (
        <InviteSheet showtime={s} apiBase={apiBase} groupId={groupId} onClose={() => setInviting(false)}
                     onDone={post => setD(prev => ({ ...prev, invite: post }))} />
      )}
    </div>
  );
}

// After adding a film to your watchlist (when your watchlist choice is "Ask"):
// may the weekly Discord digest mention you when it's playing? Only offered to
// members in the club's server.
export function WatchDiscordPrompt({ apiBase, movieId, onDone }) {
  const [error, setError] = useState("");
  const answer = async (share, remember = false) => {
    setError("");
    try {
      onDone?.(await call(apiBase, `/api/watchlist/${movieId}/discord`, "PUT", { share, remember }));
    } catch (e) {
      setError(e.message);
    }
  };
  return (
    <div className="share-prompt watch-discord-prompt" role="group" aria-label="Mention you in Discord">
      <span>Mention you in the Discord digest when it's playing?</span>
      <button type="button" className="btn btn-sm btn-primary" onClick={() => answer(true)}>Yes</button>
      <button type="button" className="btn btn-sm" onClick={() => answer(false)}>No</button>
      <span className="share-remember">
        <button type="button" className="share-link" onClick={() => answer(true, true)}>Always</button>
        {" · "}
        <button type="button" className="share-link" onClick={() => answer(false, true)}>Never ask</button>
      </span>
      {error && <p className="share-error">{error}</p>}
    </div>
  );
}

// A poll's Discord posts, for group admins: the announcement (now or later)
// and, once scored, the results. Each can be posted, rescheduled or taken down.
export function PollDiscord({ poll, apiBase, onChange }) {
  const [when, setWhen] = useState({ when: "now" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const { announce, results } = poll.discord;
  const run = async (fn) => {
    setBusy(true);
    setError("");
    try { await fn(); onChange?.(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const share = (kind, postAt) => run(() => shareToDiscord(apiBase, {
    kind, group_id: poll.group_id, poll_id: poll.id, post_at: postAt,
  }));

  return (
    <section className="poll-discord" aria-label="Discord">
      <div className="poll-discord-row">
        <span className="poll-discord-label">Announcement</span>
        {announce ? (
          <>
            <PostState post={announce} label="Announced" />
            {isScheduled(announce) && (
              <button type="button" className="share-link" disabled={busy} onClick={() => run(() => postNow(apiBase, announce.id))}>Post now</button>
            )}
            <button type="button" className="share-link" disabled={busy}
                    onClick={() => run(() => unshareFromDiscord(apiBase, announce.id))}>
              {announce.status === "posted" ? "Remove from Discord" : "Cancel"}
            </button>
          </>
        ) : (
          <>
            <ShareWhen value={when} onChange={setWhen} />
            <button type="button" className="btn btn-sm btn-primary" disabled={busy || (when.when === "later" && !when.at)}
                    onClick={() => share("poll", when.when === "later" ? when.at : undefined)}>
              {when.when === "later" ? "Schedule" : "Announce in #movies"}
            </button>
          </>
        )}
      </div>
      {poll.status === "scored" && (
        <div className={`poll-discord-row${results ? "" : " nudge"}`}>
          <span className="poll-discord-label">Results</span>
          {results ? (
            <>
              <PostState post={results} label="Results" />
              <button type="button" className="share-link" disabled={busy}
                      onClick={() => run(() => unshareFromDiscord(apiBase, results.id))}>
                {results.status === "posted" ? "Remove from Discord" : "Cancel"}
              </button>
            </>
          ) : (
            <>
              <span className="share-state">Results are in — not posted yet.</span>
              <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => share("poll_results")}>
                Post results in #movies
              </button>
            </>
          )}
        </div>
      )}
      {error && <p className="share-error">{error}</p>}
    </section>
  );
}

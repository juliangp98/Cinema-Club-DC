import { useEffect, useState } from "react";
import { getJson, send } from "../api";
import Panel from "../ui/Panel";

// Game posts waiting for an organizer's or admin's OK (R14): each exactly as it'll look in
// the club's Discord — the question of the day (with its answer, for checking) or the
// month's bingo card — with Post it / Try another or Reshuffle / Skip. The
// same buttons come in a Discord DM for those who take DMs.
const LETTERS = "ABCD";

function TriviaPreview({ post }) {
  const q = post.question;
  if (!q) return null;
  return (
    <>
      <p className="trivia-q">{q.prompt}</p>
      <ol className="game-preview-options">
        {q.options.map((o, i) => (
          <li key={o} className={i === post.answer ? "right" : ""}><strong>{LETTERS[i]}.</strong> {o}
            {i === post.answer && <span className="ui-hint"> — the answer</span>}</li>
        ))}
      </ol>
    </>
  );
}

function CardPreview({ post }) {
  return (
    <ul className="filter-chips">
      {(post.squares || []).map(s => <li key={s.key}><span className="chip" title={s.hint}>{s.emoji} {s.label}</span></li>)}
    </ul>
  );
}

// Game posts for the people who run the games (R14; skipped ones R15): what's
// waiting for an OK and what was skipped but can still go up. One loader and
// one way to act, for Club settings and Play's "Running the games" panel.
export const postTitle = post => (post.kind === "trivia" ? "🧠 Today's question of the day" : `🎱 ${post.month_label}'s bingo card`);

export function useGamePosts(apiBase, slug) {
  const [posts, setPosts] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!slug) return;
    getJson(`${apiBase}/api/groups/${slug}/game-posts`, { cache: false })
      .then(d => setPosts({ waiting: d.waiting, skipped: d.skipped || [] }))
      .catch(() => setPosts({ waiting: [], skipped: [] }));
  }, [apiBase, slug]);

  async function act(post, action) {
    setBusy(true);
    setError(null);
    try {
      const d = await send(`${apiBase}/api/groups/${slug}/game-posts/${post.id}`, "POST", { action });
      setPosts(prev => {
        const rest = list => list.filter(p => p.id !== d.id);
        return { waiting: d.status === "waiting" ? prev.waiting.map(p => (p.id === d.id ? d : p)) : rest(prev.waiting),
                 skipped: d.status === "skipped" && d.until ? [...rest(prev.skipped), d] : rest(prev.skipped) };
      });
    } catch (e) {
      setError(e.data?.error || "Couldn't do that — try again.");
      if (e.data?.id) setPosts(prev => ({ ...prev, waiting: prev.waiting.map(p => (p.id === post.id ? e.data : p)) }));
    } finally { setBusy(false); }
  }
  return { posts, error, busy, act };
}

export function SkippedPosts({ skipped, busy, act }) {
  if (!skipped?.length) return null;
  return (
    <ul className="game-skipped">
      {skipped.map(post => (
        <li key={post.id}>
          <span>{postTitle(post)} <span className="ui-hint">· skipped — it can still go up until {post.until}</span></span>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => act(post, "post")}>Post it after all</button>
        </li>
      ))}
    </ul>
  );
}

export default function GamePostsWaiting({ apiBase, slug }) {
  const { posts, error, busy, act } = useGamePosts(apiBase, slug);
  if (!posts || (!posts.waiting.length && !posts.skipped.length)) return null;
  return (
    <section id="game-posts" aria-labelledby="game-posts-title">
      {error && <p className="share-error" role="alert">{error}</p>}
      {posts.waiting.length > 0 && <h3 className="club-settings-sub" id="game-posts-title">Waiting for your OK</h3>}
      {posts.waiting.map(post => (
        <Panel key={post.id} tone="gold" className="game-preview" titleId={`game-post-${post.id}`}
               aria-labelledby={`game-post-${post.id}`} title={postTitle(post)} hint="As it'll look in Discord"
               actions={<>
                 <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => act(post, "post")}>Post it</button>
                 {post.kind === "trivia" && (
                   <button type="button" className="btn btn-sm" disabled={busy || !post.can_swap} onClick={() => act(post, "another")}
                           title={post.can_swap ? undefined : "Someone has answered it already"}>Try another</button>
                 )}
                 {post.kind === "bingo_card" && (
                   <button type="button" className="btn btn-sm" disabled={busy} onClick={() => act(post, "reshuffle")}>Reshuffle</button>
                 )}
                 <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => act(post, "skip")}>Skip</button>
               </>}>
          {post.kind === "trivia" ? <TriviaPreview post={post} /> : <CardPreview post={post} />}
        </Panel>
      ))}
      {posts.skipped.length > 0 && <h3 className="club-settings-sub" id={posts.waiting.length ? undefined : "game-posts-title"}>Skipped</h3>}
      <SkippedPosts skipped={posts.skipped} busy={busy} act={act} />
    </section>
  );
}

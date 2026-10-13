import { useEffect, useState } from "react";
import { getJson, send } from "../api";
import Panel from "../ui/Panel";
import { SectionTitle } from "../ui/PageHeader";
import useHashScroll from "../useHashScroll";

// Game posts waiting for an admin's OK (R14): each exactly as it'll look in
// #movies — the question of the day (with its answer, for checking) or the
// month's bingo card — with Post it / Try another or Reshuffle / Skip. The
// same buttons come in a Discord DM for admins who take DMs.
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

export default function GamePostsWaiting({ apiBase, slug }) {
  const [posts, setPosts] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    getJson(`${apiBase}/api/groups/${slug}/game-posts`, { cache: false }).then(d => setPosts(d.waiting)).catch(() => setPosts([]));
  }, [apiBase, slug]);
  useHashScroll(!!posts?.length);              // the bell's link: /club?tab=settings#game-posts
  if (!posts?.length) return null;

  async function act(post, action) {
    setBusy(true);
    setError(null);
    try {
      const d = await send(`${apiBase}/api/groups/${slug}/game-posts/${post.id}`, "POST", { action });
      setPosts(prev => (d.status === "waiting" ? prev.map(p => (p.id === post.id ? d : p)) : prev.filter(p => p.id !== post.id)));
    } catch (e) {
      setError(e.data?.error || "Couldn't do that — try again.");
      if (e.data?.id) setPosts(prev => prev.map(p => (p.id === post.id ? e.data : p)));
    } finally { setBusy(false); }
  }
  return (
    <section id="game-posts" aria-labelledby="game-posts-title">
      <SectionTitle><span id="game-posts-title">Waiting for your OK</span></SectionTitle>
      {error && <p className="share-error" role="alert">{error}</p>}
      {posts.map(post => (
        <Panel key={post.id} tone="gold" className="game-preview" titleId={`game-post-${post.id}`}
               aria-labelledby={`game-post-${post.id}`}
               title={post.kind === "trivia" ? "🧠 Today's question of the day" : `🎱 ${post.month_label}'s bingo card`}
               hint="As it'll look in #movies"
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
    </section>
  );
}

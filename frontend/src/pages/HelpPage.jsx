import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import Panel from "../ui/Panel";
import RichText from "../ui/RichText";
import { useShell } from "../shell/AppShell";
import { send } from "../api";
import { SECTIONS, TOPICS, plain, rank, words } from "../help";

// The help guide (R11): one searchable page, a section per area of the site,
// each a few questions with short answers — in help.json (7f), with links
// straight to the place in the site. Deep links: /help#<section> or
// /help#<topic>, which opens it and lights it up. Typing filters as you go;
// signed-in accounts can also ✨ Ask in their own words (the AI answers from
// these topics only). Keep it in step with the site — if a feature changes,
// change its answer.

const norm = s => s.toLowerCase();
const text = (sec, item) => norm(`${sec.title} ${item.q} ${plain(item.a)}`);

function Answer({ a }) {
  if (a.loading) return <Panel tone="gold" className="help-answer" title="✨ Thinking…" />;
  return (
    <Panel tone="gold" className="help-answer" title={a.answer ? "✨ AI answer" : "✨ Best matches"}
           hint={a.answer ? "From the topics below — AI can get things wrong" : a.note}>
      {a.answer && <p><RichText text={a.answer} /></p>}
      {a.topics?.length > 0 && (
        <ul className="help-answer-topics">
          {a.topics.filter(id => TOPICS[id]).map(id => <li key={id}><Link to={`/help#${id}`}>{TOPICS[id].q}</Link></li>)}
        </ul>
      )}
    </Panel>
  );
}

export default function HelpPage({ apiBase = "" }) {
  const shell = useShell() || {};
  const [q, setQ] = useState("");
  const [asked, setAsked] = useState(null);           // {q, loading} or the answer
  const canAsk = !!shell.user && !shell.user.is_guest;
  const shown = useMemo(() => {
    const ws = norm(q).split(/\s+/).filter(Boolean);
    if (!ws.length) return SECTIONS;
    return SECTIONS.map(sec => ({ ...sec, items: sec.items.filter(item => ws.every(w => text(sec, item).includes(w))) }))
      .filter(sec => sec.items.length);
  }, [q]);
  const near = useMemo(() => (q && !shown.length ? rank(q) : []), [q, shown.length]);

  async function ask(e) {
    e.preventDefault();
    const question = q.trim();
    if (!canAsk || words(question).length < 2 || asked?.q === question) return;
    setAsked({ q: question, loading: true });
    try {
      setAsked({ q: question, ...(await send(`${apiBase}/api/help/ask`, "POST", { q: question })) });
    } catch (err) {
      setAsked({ q: question, topics: rank(question).map(i => i.id), note: err.data?.error || "Couldn't ask right now — here are the closest topics." });
    }
  }

  return (
    <div className="page narrow help-page">
      <PageHeader title="Help" />
      <form className="help-tools" onSubmit={ask} role="search">
        <input type="search" className="share-input help-search"
               placeholder={canAsk ? "Search, or ask a question (kernels, Discord, alerts…)" : "Search help (kernels, Discord, alerts…)"}
               aria-label="Search help" value={q} onChange={e => { setQ(e.target.value); if (!e.target.value) setAsked(null); }} />
        {canAsk && <button type="submit" className="btn btn-sm btn-primary" disabled={words(q).length < 2}>✨ Ask</button>}
        {shell.user && !shell.user.is_guest && (
          <button type="button" className="btn btn-sm" onClick={() => shell.startTour?.()}>Take the tour</button>
        )}
      </form>
      {asked && asked.q === q.trim() && <Answer a={asked} />}
      {!q && (
        <nav className="help-toc" aria-label="Help topics">
          {SECTIONS.map(s => <a key={s.id} href={`#${s.id}`} className="chip">{s.title}</a>)}
        </nav>
      )}
      {shown.length === 0 && !(asked && asked.q === q.trim()) && (
        <div className="pv-empty">
          <p>Nothing has every word of “{q}”.{canAsk ? " Tap ✨ Ask to ask it in your own words" : ""}
            {near.length ? (canAsk ? ", or try the closest topics:" : " The closest topics:") : "."}{" "}
            {!near.length && <Link to="/help" onClick={() => setQ("")}>See every topic</Link>}</p>
          {near.length > 0 && (
            <ul className="help-answer-topics">
              {near.map(i => <li key={i.id}><Link to={`/help#${i.id}`} onClick={() => setQ("")}>{i.q}</Link></li>)}
            </ul>
          )}
        </div>
      )}
      {shown.map(sec => (
        <section key={sec.id} id={sec.id} className="help-section">
          <h2 className="help-title">{sec.title}</h2>
          {sec.items.map(item => (
            <details key={item.id} id={item.id} className="help-item" open={!!q}>
              <summary>{item.q}</summary>
              <p><RichText text={item.a} /></p>
            </details>
          ))}
        </section>
      ))}
    </div>
  );
}

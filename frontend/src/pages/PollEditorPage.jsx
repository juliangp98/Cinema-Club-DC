import { useState, useEffect } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import { Segmented } from "../ui/TicketRow";
import { ShareWhen } from "../ui/DiscordShare";
import { useShell } from "../shell/AppShell";
import { SCORING_LABELS } from "./PollsPage";
import "./Polls.css";

const TYPES = [{ status: "standard", label: "Opinion" }, { status: "prediction", label: "Prediction" }];
const MODES = {
  standard: [{ status: "none", label: "Plain vote" }, { status: "ranked", label: "Ranked top 3" }],
  prediction: [{ status: "single", label: "1 🍿 per correct" }, { status: "confidence", label: "Confidence × 🍿" },
               { status: "ranked", label: "Ranked top 3" }],
};
// What a draft is based on: the club's local showings, or films in general.
const SCOPES = [{ status: "playing", label: "Local showings" }, { status: "all", label: "All films" }];
const SCOPE_KEY = "cinemaclub_draft_scope";
const EXAMPLES = ["Spookiest Halloween movies playing this month", "The 99th Oscar winners", "Best repertory screening this fall"];
const blankCategory = () => ({ title: "", options: [{ text: "" }, { text: "" }] });

// New poll (R6a): describe it and the AI drafts it, or build it by hand —
// either way you edit everything before it's created. ?draft=<id> opens a
// draft made in Discord (/poll make).
export default function PollEditorPage({ apiBase, activeGroupId }) {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const shell = useShell();
  const canRun = ["organizer", "admin"].includes(shell?.role);
  const [ask, setAsk] = useState("");
  const [scope, setScopeState] = useState(() => { try { return localStorage.getItem(SCOPE_KEY) === "all" ? "all" : "playing"; } catch { return "playing"; } });
  const setScope = v => { if (!v) return; setScopeState(v); try { localStorage.setItem(SCOPE_KEY, v); } catch { /* private mode */ } };
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState("");
  const [form, setForm] = useState({ title: "", description: "", poll_type: "standard", scoring_mode: "none",
                                     categories: [blankCategory()] });
  const [draftId, setDraftId] = useState(null);
  const [notes, setNotes] = useState("");
  const [announce, setAnnounce] = useState(() => ({ when: shell?.user?.share_prefs?.poll === "never" ? "none" : "now" }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function applyDraft(d) {
    setForm({ title: d.title, description: d.description || "", poll_type: d.poll_type, scoring_mode: d.scoring_mode,
              categories: d.categories.map(c => ({ title: c.title, options: c.options.map(o => ({ text: o.text, extra: o.extra })) })) });
    setDraftId(d.id);
    setNotes(d.notes || "");
  }

  // A draft from Discord's "Open in editor".
  useEffect(() => {
    const id = params.get("draft");
    if (!id) return;
    fetch(`${apiBase}/api/poll-drafts/${id}`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(d => { applyDraft(d); setAsk(d.prompt || ""); if (d.scope) setScopeState(d.scope); })
      .catch(() => setDraftError("That draft couldn't be opened (it may belong to another club)."));
  }, [apiBase, params]);

  async function draft(e) {
    e?.preventDefault();
    if (ask.trim().length < 3) return;
    setDrafting(true);
    setDraftError("");
    const r = await fetch(`${apiBase}/api/groups/${activeGroupId}/polls/draft`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
      body: JSON.stringify({ prompt: ask, scope }),
    }).catch(() => null);
    const d = r ? await r.json().catch(() => ({})) : {};
    setDrafting(false);
    if (r?.ok) applyDraft(d);
    else setDraftError(d.error || "Couldn't draft that right now. You can still build the poll by hand below.");
  }

  const set = changes => setForm(f => ({ ...f, ...changes }));
  const setCat = (i, changes) => set({ categories: form.categories.map((c, j) => (j === i ? { ...c, ...changes } : c)) });
  const setOpt = (i, k, text) => setCat(i, { options: form.categories[i].options.map((o, j) => (j === k ? { text } : o)) });
  const move = (list, from, to) => { const next = [...list]; const [x] = next.splice(from, 1); next.splice(to, 0, x); return next; };

  function setType(t) {
    if (!t) return;
    set({ poll_type: t, scoring_mode: MODES[t].some(m => m.status === form.scoring_mode) ? form.scoring_mode : MODES[t][0].status });
  }

  const ready = form.title.trim() && form.categories.some(c => c.title.trim() && c.options.filter(o => o.text.trim()).length >= 2);

  async function create() {
    setSaving(true);
    setError("");
    const body = {
      ...form,
      categories: form.categories
        .map(c => ({ title: c.title.trim(), options: c.options.filter(o => o.text.trim()).map(o => ({ text: o.text.trim(), extra: o.extra })) }))
        .filter(c => c.title && c.options.length >= 2),
      draft_id: draftId,
      ...(shell?.group?.discord ? { announce: announce.when, announce_at: announce.when === "later" ? announce.at : undefined } : {}),
    };
    const r = await fetch(`${apiBase}/api/groups/${activeGroupId}/polls`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include", body: JSON.stringify(body),
    }).catch(() => null);
    const d = r ? await r.json().catch(() => ({})) : {};
    setSaving(false);
    if (r?.ok) navigate(`/polls/${d.id}`);
    else setError(d.error || "Couldn't create the poll — try again.");
  }

  async function oscars() {
    const r = await fetch(`${apiBase}/api/groups/${activeGroupId}/polls/oscars`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
      body: JSON.stringify({ scoring_mode: "confidence" }),
    }).catch(() => null);
    if (r?.ok) navigate(`/polls/${(await r.json()).id}`);
  }

  if (!canRun) {
    return (
      <div className="page narrow">
        <PageHeader title="New poll" back={{ to: "/polls", label: "Polls" }} />
        <p className="pv-empty">Organizers and admins make polls. Ask a club admin for the Organizer role.</p>
      </div>
    );
  }

  return (
    <div className="page narrow polls">
      <PageHeader title="New poll" back={{ to: "/polls", label: "Polls" }} />

      <form className="pv-ask" onSubmit={draft}>
        <label className="pv-label" htmlFor="pv-ask">Describe the poll you want</label>
        <div className="pv-ask-row">
          <input id="pv-ask" className="share-input" value={ask} maxLength={300} onChange={e => setAsk(e.target.value)}
                 placeholder="e.g. spookiest Halloween movies playing this month" />
          <button className="btn btn-primary" disabled={drafting || ask.trim().length < 3}>{drafting ? "Drafting…" : "✨ Draft it"}</button>
        </div>
        <div className="pv-scope">
          <span className="pv-label">Based on</span>
          <Segmented label="Based on" options={SCOPES} value={scope} onChange={setScope} />
          <span className="pv-hint">{scope === "playing" ? "Options come from films playing at the club's theatres." : "Any films — not tied to what's playing."}</span>
        </div>
        <div className="pv-examples">
          {EXAMPLES.map(x => <button key={x} type="button" className="chip" onClick={() => setAsk(x)}>{x}</button>)}
          <button type="button" className="chip" onClick={oscars}>🏆 Oscars template</button>
        </div>
        {drafting && <p className="pv-hint">The AI is drafting it{scope === "playing" ? " from what's playing" : ""}, which takes a few seconds.</p>}
        {draftError && <p className="share-error">{draftError}</p>}
        {draftId && !drafting && <p className="pv-hint">Drafted. Edit anything below, then create it.</p>}
        {notes && <p className="pv-note">⚠️ {notes}</p>}
      </form>

      <SectionTitle>The poll</SectionTitle>
      <div className="pv-form">
        <label className="pv-label" htmlFor="pv-title">Title</label>
        <input id="pv-title" className="share-input" value={form.title} maxLength={120} onChange={e => set({ title: e.target.value })} />
        <label className="pv-label" htmlFor="pv-desc">Description (optional)</label>
        <textarea id="pv-desc" className="share-input" rows={2} value={form.description} maxLength={400} onChange={e => set({ description: e.target.value })} />
        <div className="pv-row">
          <div>
            <span className="pv-label">Type</span>
            <Segmented label="Type" options={TYPES} value={form.poll_type} onChange={setType} />
          </div>
          <div>
            <span className="pv-label">Scoring</span>
            <Segmented label="Scoring" options={MODES[form.poll_type]} value={form.scoring_mode} onChange={v => v && set({ scoring_mode: v })} />
          </div>
        </div>
        <p className="pv-hint">
          {form.poll_type === "prediction" ? "Has right answers you'll mark later; correct picks earn 🍿." : "Opinions: no right answers."}
          {" "}{SCORING_LABELS[form.scoring_mode]}.
        </p>

        {form.categories.map((c, i) => (
          <fieldset key={i} className="pv-edit-cat">
            <div className="pv-edit-cat-head">
              <input className="share-input" placeholder={`Category ${i + 1} (e.g. Best Picture)`} value={c.title} maxLength={200}
                     onChange={e => setCat(i, { title: e.target.value })} aria-label={`Category ${i + 1} title`} />
              <button type="button" className="share-link" disabled={i === 0} onClick={() => set({ categories: move(form.categories, i, i - 1) })} aria-label="Move up">↑</button>
              <button type="button" className="share-link" disabled={i === form.categories.length - 1} onClick={() => set({ categories: move(form.categories, i, i + 1) })} aria-label="Move down">↓</button>
              {form.categories.length > 1 && (
                <button type="button" className="share-link" onClick={() => set({ categories: form.categories.filter((_, j) => j !== i) })}>Remove</button>
              )}
            </div>
            {c.options.map((o, k) => (
              <div key={k} className="pv-edit-opt">
                {o.extra?.poster_url ? <img src={o.extra.poster_url} alt="" /> : <span className="pv-edit-opt-dot" />}
                <input className="share-input" placeholder={`Option ${k + 1}`} value={o.text} maxLength={200}
                       onChange={e => setOpt(i, k, e.target.value)} aria-label={`Category ${i + 1} option ${k + 1}`} />
                {c.options.length > 2 && (
                  <button type="button" className="share-link" aria-label="Remove option"
                          onClick={() => setCat(i, { options: c.options.filter((_, j) => j !== k) })}>×</button>
                )}
              </div>
            ))}
            {c.options.length < 15 && (
              <button type="button" className="share-link" onClick={() => setCat(i, { options: [...c.options, { text: "" }] })}>＋ Option</button>
            )}
          </fieldset>
        ))}
        {form.categories.length < 25 && (
          <button type="button" className="btn btn-sm" onClick={() => set({ categories: [...form.categories, blankCategory()] })}>＋ Category</button>
        )}

        {shell?.group?.discord && (
          <div className="pv-announce">
            <span className="pv-label">Announce in #movies</span>
            <ShareWhen value={announce} onChange={setAnnounce} allowNone />
          </div>
        )}
        {error && <p className="share-error">{error}</p>}
        <div className="pv-form-foot">
          <Link className="btn btn-ghost" to="/polls">Cancel</Link>
          <button className="btn btn-primary" onClick={create} disabled={!ready || saving || (announce.when === "later" && !announce.at)}>
            {saving ? "Creating…" : "Create poll"}
          </button>
        </div>
      </div>
    </div>
  );
}

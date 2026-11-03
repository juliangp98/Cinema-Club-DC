import { useState, useEffect } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { getJson, send } from "../api";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import { Segmented } from "../ui/TicketRow";
import { ShareWhen } from "../ui/DiscordShare";
import { useShell } from "../shell/AppShell";
import { SCORING_LABELS, TYPE_LABELS, REVEAL_LABELS, REVEAL_HINTS } from "../components/PollList";
import "./Polls.css";
import { runsClub } from "../roles";

const TYPES = [{ status: "standard", label: "Opinion" }, { status: "prediction", label: "Prediction" }];
const MODES = {
  standard: [{ status: "none", label: "Plain vote" }, { status: "ranked", label: "Ranked top 3" }],
  prediction: [{ status: "single", label: "1 🍿 per correct" }, { status: "confidence", label: "Confidence × 🍿" },
               { status: "ranked", label: "Ranked top 3" }],
};
const REVEALS = [{ status: "final", label: REVEAL_LABELS.final }, { status: "live", label: REVEAL_LABELS.live }];
const DEADLINES = [{ status: "manual", label: "When I close it" }, { status: "at", label: "At a set time" }];
// What a draft is based on: the club's local showings, or films in general.
const SCOPES = [{ status: "playing", label: "Local showings" }, { status: "all", label: "All films" }];
const SCOPE_KEY = "cinemaclub_draft_scope";
const EXAMPLES = ["Spookiest Halloween movies playing this month", "The 99th Oscar nominees", "Best repertory screening this fall"];
const blankCategory = () => ({ title: "", options: [{ text: "" }, { text: "" }] });
const BLANK = { title: "", description: "", poll_type: "standard", scoring_mode: "none", reveal: "final", closes: "",
                categories: [blankCategory()] };

// <input type="datetime-local"> value an hour or so from now (the default deadline).
function soon() {
  const d = new Date(Date.now() + 2 * 60 * 60 * 1000);
  d.setMinutes(0, 0, 0);
  const pad = n => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
}

// New poll (R6a): describe it and the AI drafts it, or build it by hand —
// either way you edit everything before it's created. ?draft=<id> opens a
// draft made in Discord (/poll make). /polls/<id>/edit is the same form for
// a poll that exists: fix names, add or remove categories and nominees,
// change the deadline — and, until someone votes, how it's scored.
export default function PollEditorPage({ apiBase, activeGroupId }) {
  const navigate = useNavigate();
  const { pollId } = useParams();
  const editing = !!pollId;
  const [params] = useSearchParams();
  const shell = useShell();
  const canRun = runsClub(shell?.role);
  const [ask, setAsk] = useState("");
  const [scope, setScopeState] = useState(() => { try { return localStorage.getItem(SCOPE_KEY) === "all" ? "all" : "playing"; } catch { return "playing"; } });
  const setScope = v => { if (!v) return; setScopeState(v); try { localStorage.setItem(SCOPE_KEY, v); } catch { /* private mode */ } };
  const [drafting, setDrafting] = useState(false);
  const [draftError, setDraftError] = useState("");
  const [form, setForm] = useState(BLANK);
  const [poll, setPoll] = useState(null);              // editing: the poll as it is
  const [draftId, setDraftId] = useState(null);
  const [notes, setNotes] = useState("");
  const [announce, setAnnounce] = useState(() => ({ when: shell?.user?.share_prefs?.poll === "never" ? "none" : "now" }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  // Only members in the club's Discord server (with Discord linked) can announce there.
  const canAnnounce = !editing && !!(shell?.group?.discord && shell?.user?.discord_clubs?.includes(shell.group.id));
  const scoringSet = editing && poll?.has_votes;      // members have picked: how it's scored stays
  const showDeadline = !editing || poll?.status === "open";

  function applyDraft(d) {
    setForm(f => ({ ...f, title: d.title, description: d.description || "", poll_type: d.poll_type, scoring_mode: d.scoring_mode,
                    categories: d.categories.map(c => ({ title: c.title, options: c.options.map(o => ({ text: o.text, extra: o.extra })) })) }));
    setDraftId(d.id);
    setNotes(d.notes || "");
  }

  // A draft from Discord's "Open in editor".
  useEffect(() => {
    const id = params.get("draft");
    if (!id || editing) return;
    getJson(`${apiBase}/api/poll-drafts/${id}`)
      .then(d => { applyDraft(d); setAsk(d.prompt || ""); if (d.scope) setScopeState(d.scope); })
      .catch(() => setDraftError("That draft couldn't be opened (it may belong to another club)."));
  }, [apiBase, params, editing]);

  // Editing: the poll as it stands.
  useEffect(() => {
    if (!editing) return;
    getJson(`${apiBase}/api/polls/${pollId}`, { cache: false }).then(p => {
      setPoll(p);
      setForm({ title: p.title, description: p.description || "", poll_type: p.poll_type, scoring_mode: p.scoring_mode,
                reveal: p.reveal || "final", closes: p.status === "open" ? (p.closes_at_local || "") : "",
                categories: p.categories.map(c => ({ id: c.id, title: c.title, picked: c.vote_count > 0,
                                                     options: c.options.map(o => ({ id: o.id, text: o.text, extra: o.extra })) })) });
    }).catch(() => setError("That poll couldn't be opened."));
  }, [apiBase, pollId, editing]);

  async function draft(e) {
    e?.preventDefault();
    if (ask.trim().length < 3) return;
    setDrafting(true);
    setDraftError("");
    try {
      applyDraft(await send(`${apiBase}/api/groups/${activeGroupId}/polls/draft`, "POST", { prompt: ask, scope }));
    } catch (e) {
      setDraftError(e.data?.error || "Couldn't draft that right now. You can still build the poll by hand below.");
    } finally { setDrafting(false); }
  }

  const set = changes => setForm(f => ({ ...f, ...changes }));
  const setCat = (i, changes) => set({ categories: form.categories.map((c, j) => (j === i ? { ...c, ...changes } : c)) });
  // Renaming keeps the nominee (its picks, and its poster when the AI linked a film).
  const setOpt = (i, k, text) => setCat(i, { options: form.categories[i].options.map((o, j) => (j === k ? { ...o, text } : o)) });
  const move = (list, from, to) => { const next = [...list]; const [x] = next.splice(from, 1); next.splice(to, 0, x); return next; };

  function setType(t) {
    if (!t) return;
    set({ poll_type: t, scoring_mode: MODES[t].some(m => m.status === form.scoring_mode) ? form.scoring_mode : MODES[t][0].status });
  }

  const scored = form.scoring_mode !== "none";
  const deadline = form.closes ? "at" : "manual";
  const ready = form.title.trim() && form.categories.some(c => c.title.trim() && c.options.filter(o => o.text.trim()).length >= 2);

  async function save() {
    setSaving(true);
    setError("");
    const categories = form.categories
      .map(c => ({ ...(c.id ? { id: c.id } : {}), title: c.title.trim(),
                   options: c.options.filter(o => o.text.trim()).map(o => ({ ...(o.id ? { id: o.id } : {}), text: o.text.trim(), extra: o.extra })) }))
      .filter(c => c.title && c.options.length >= 2);
    const body = {
      title: form.title, description: form.description, categories, ...(showDeadline ? { closes_at: form.closes || null } : {}),
      ...(scoringSet ? {} : { poll_type: form.poll_type, scoring_mode: form.scoring_mode, reveal: scored ? form.reveal : "final" }),
    };
    try {
      if (editing) {
        await send(`${apiBase}/api/polls/${pollId}`, "PUT", body);
        navigate(`/polls/${pollId}`);
      } else {
        const made = await send(`${apiBase}/api/groups/${activeGroupId}/polls`, "POST", {
          ...body, draft_id: draftId,
          ...(canAnnounce ? { announce: announce.when, announce_at: announce.when === "later" ? announce.at : undefined } : {}),
        });
        navigate(`/polls/${made.id}`);
      }
    } catch (e) {
      setError(e.data?.error || (editing ? "Couldn't save the changes — try again." : "Couldn't create the poll — try again."));
    } finally { setSaving(false); }
  }

  async function remove() {
    const warn = poll?.status === "scored" ? " Members lose the kernels it gave them." : "";
    if (!window.confirm(`Delete this poll? Its votes go too, and this can't be undone.${warn}`)) return;
    try {
      await send(`${apiBase}/api/polls/${pollId}`, "DELETE");
      navigate("/play#polls");
    } catch (e) { setError(e.data?.error || "Couldn't delete it — try again."); }
  }

  const back = editing ? { to: `/polls/${pollId}`, label: "The poll" } : { to: "/play#polls", label: "Play" };
  if (!canRun) {
    return (
      <div className="page">
        <PageHeader title={editing ? "Edit poll" : "New poll"} back={back} />
        <p className="pv-empty">Organizers and admins make polls. Ask a club admin for the Organizer role.</p>
      </div>
    );
  }
  if (editing && !poll) {
    return (
      <div className="page">
        <PageHeader title="Edit poll" back={back} />
        {error ? <p className="share-error">{error}</p> : <p className="pv-empty">Loading…</p>}
      </div>
    );
  }

  return (
    <div className="page polls">
      <PageHeader title={editing ? "Edit poll" : "New poll"} back={back} />

      {!editing && (
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
            <span className="ui-hint">{scope === "playing" ? "Options come from films playing at the club's theatres." : "Any films — not tied to what's playing."}</span>
          </div>
          <div className="pv-examples">
            {EXAMPLES.map(x => <button key={x} type="button" className="chip" onClick={() => setAsk(x)}>{x}</button>)}
          </div>
          {drafting && <p className="ui-hint">The AI is drafting it{scope === "playing" ? " from what's playing" : ""}, which takes a few seconds.</p>}
          {draftError && <p className="share-error">{draftError}</p>}
          {draftId && !drafting && <p className="ui-hint">Drafted. Edit anything below, then create it.</p>}
          {notes && <p className="pv-note">⚠️ {notes}</p>}
        </form>
      )}

      <SectionTitle>The poll</SectionTitle>
      <div className="pv-form">
        <label className="pv-label" htmlFor="pv-title">Title</label>
        <input id="pv-title" className="share-input" value={form.title} maxLength={120} onChange={e => set({ title: e.target.value })} />
        <label className="pv-label" htmlFor="pv-desc">Description (optional)</label>
        <textarea id="pv-desc" className="share-input" rows={2} value={form.description} maxLength={400} onChange={e => set({ description: e.target.value })} />
        {scoringSet ? (
          <div className="pv-set">
            <span className="pv-label">How it's scored</span>
            <p>{TYPE_LABELS[form.poll_type]} · {SCORING_LABELS[form.scoring_mode]}{scored ? ` · Answers: ${REVEAL_LABELS[form.reveal].toLowerCase()}` : ""}</p>
            <p className="ui-hint">Members have voted, so this stays as it is — their picks were made for it.</p>
          </div>
        ) : (
          <>
            <div className="pv-row">
              <div>
                <span className="pv-label">Type</span>
                <Segmented label="Type" options={TYPES} value={form.poll_type} onChange={setType} />
              </div>
              <div>
                <span className="pv-label">Scoring</span>
                <Segmented label="Scoring" options={MODES[form.poll_type]} value={form.scoring_mode} onChange={v => v && set({ scoring_mode: v })} />
              </div>
              {scored && (
                <div>
                  <span className="pv-label">Show answers</span>
                  <Segmented label="Show answers" options={REVEALS} value={form.reveal} onChange={v => v && set({ reveal: v })} />
                </div>
              )}
            </div>
            <p className="ui-hint">
              {form.poll_type === "prediction" ? "Has right answers you'll mark later; correct picks earn 🍿." : "Opinions: no right answers."}
              {" "}{SCORING_LABELS[form.scoring_mode]}.{scored ? ` ${REVEAL_HINTS[form.reveal]}` : ""}
            </p>
          </>
        )}

        {showDeadline && <div className="pv-deadline">
          <span className="pv-label">Voting closes</span>
          <div className="pv-deadline-row">
            <Segmented label="Voting closes" options={DEADLINES} value={deadline}
                       onChange={v => v && set({ closes: v === "at" ? (form.closes || soon()) : "" })} />
            {deadline === "at" && (
              <input type="datetime-local" className="share-input pv-deadline-at" value={form.closes} aria-label="Voting closes at"
                     onChange={e => set({ closes: e.target.value })} />
            )}
          </div>
          <p className="ui-hint">
            {deadline === "at" ? "It closes by itself then, on the club's clock — set it to when the ceremony or the weekend starts."
                               : "Open until you tap Close voting."}
          </p>
        </div>}

        {form.categories.map((c, i) => (
          <fieldset key={c.id || `new-${i}`} className="pv-edit-cat">
            <div className="pv-edit-cat-head">
              <input className="share-input" placeholder={`Category ${i + 1} (e.g. Best Picture)`} value={c.title} maxLength={200}
                     onChange={e => setCat(i, { title: e.target.value })} aria-label={`Category ${i + 1} title`} />
              <button type="button" className="share-link" disabled={i === 0} onClick={() => set({ categories: move(form.categories, i, i - 1) })} aria-label="Move up">↑</button>
              <button type="button" className="share-link" disabled={i === form.categories.length - 1} onClick={() => set({ categories: move(form.categories, i, i + 1) })} aria-label="Move down">↓</button>
              {form.categories.length > 1 && !c.picked && (
                <button type="button" className="share-link" onClick={() => set({ categories: form.categories.filter((_, j) => j !== i) })}>Remove</button>
              )}
            </div>
            {c.options.map((o, k) => (
              <div key={o.id || `new-${k}`} className="pv-edit-opt">
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
        {editing && <p className="ui-hint">Rename anything any time. A category or nominee someone has picked can't be removed.</p>}

        {canAnnounce && (
          <div className="pv-announce">
            <span className="pv-label">Announce in Discord</span>
            <ShareWhen value={announce} onChange={setAnnounce} allowNone />
          </div>
        )}
        {error && <p className="share-error">{error}</p>}
        <div className="pv-form-foot">
          {editing && <button type="button" className="btn btn-ghost pv-danger" onClick={remove}>Delete poll</button>}
          <Link className="btn btn-ghost" to={back.to}>Cancel</Link>
          <button className="btn btn-primary" onClick={save} disabled={!ready || saving || (announce.when === "later" && !announce.at && canAnnounce)}>
            {saving ? "Saving…" : editing ? "Save changes" : "Create poll"}
          </button>
        </div>
      </div>
    </div>
  );
}

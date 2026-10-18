import { useState } from "react";
import { Navigate } from "react-router-dom";
import { useShell } from "../shell/AppShell";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import Panel from "../ui/Panel";
import Prompt from "../ui/Prompt";
import ToggleChip, { RemovableChip } from "../ui/ToggleChip";
import { Segmented, ASK_ALWAYS_NEVER, POST_MODES } from "../ui/TicketRow";
import Avatar, { ClubBadge } from "../ui/Avatar";
import SearchField, { SearchAction } from "../ui/SearchField";
import "./StyleguidePage.css";

// The style guide (R15), for club admins: every piece of the UI kit in one
// place, live, so new features pick from here instead of inventing their own.
// Nothing on it saves anything. Linked from Club → Settings.
const BADGES = [["", "Closed"], ["go", "Going"], ["gold", "Maybe"], ["strong", "Saw it"], ["discord", "via Discord"],
                ["solid", "3 tonight"]];

export default function StyleguidePage() {
  const shell = useShell();
  const [seg, setSeg] = useState("ask");
  const [mode, setMode] = useState("never");
  const [on, setOn] = useState(true);
  const [picked, setPicked] = useState(["Agnès Varda", "Wong Kar-wai"]);
  const [find, setFind] = useState("");
  if (!shell?.group) return null;
  if (shell.role !== "admin") return <Navigate to="/club" replace />;
  const me = { name: "Your Name", id: 1 };

  return (
    <div className="page styleguide">
      <PageHeader title="Style guide" back={{ to: "/club?tab=settings", label: "Club settings" }}
                  meta={[{ label: "UI kit", gold: true }, { label: "Admins only" }, { label: "Nothing here saves" }]} />
      <p className="ui-note">The pieces every page is built from. Reach for these before writing new CSS.</p>

      <SectionTitle link={{ to: "/club?tab=settings", label: "A section link →" }}>Headings</SectionTitle>
      <p className="ui-hint">PageHeader (title, back link, meta chips) and SectionTitle (with an optional link at its end).</p>

      <SectionTitle>Buttons</SectionTitle>
      <div className="styleguide-row">
        <button type="button" className="btn btn-primary">Primary</button>
        <button type="button" className="btn">Default</button>
        <button type="button" className="btn btn-ghost">Ghost</button>
        <button type="button" className="btn btn-danger">Danger</button>
        <button type="button" className="btn btn-discord">Discord</button>
        <button type="button" className="btn" disabled>Disabled</button>
      </div>
      <div className="styleguide-row">
        <button type="button" className="btn btn-sm btn-primary">Small</button>
        <button type="button" className="btn btn-sm">Small</button>
        <button type="button" className="btn btn-lg">Large</button>
        <button type="button" className="linkish">A link-style button</button>
      </div>

      <SectionTitle>Chips and badges</SectionTitle>
      <div className="styleguide-row">
        <span className="chip">Chip</span>
        <span className="chip gold">Gold chip</span>
        <ToggleChip on={on} onClick={() => setOn(v => !v)} count={12}>Toggle chip</ToggleChip>
        {picked.map(p => <RemovableChip key={p} label={p} onRemove={() => setPicked(xs => xs.filter(x => x !== p))}>{p}</RemovableChip>)}
      </div>
      <div className="styleguide-row">
        {BADGES.map(([tone, label]) => <span key={label} className={`ui-badge ${tone}`}>{label}</span>)}
      </div>
      <p className="ui-hint">Chips are things you can pick or that describe; badges (.ui-badge) are small status labels.</p>

      <SectionTitle>Choices</SectionTitle>
      <div className="styleguide-row">
        <Segmented label="Ask / Always / Never" options={ASK_ALWAYS_NEVER} value={seg} onChange={v => setSeg(v || "ask")} />
        <Segmented label="Club posts" options={POST_MODES} value={mode} onChange={v => setMode(v || "never")} />
      </div>

      <SectionTitle>Search</SectionTitle>
      <p className="ui-hint">One search bar everywhere (ui/SearchField): Discover, Browse, the Calendar, Help, Your taste, Find a club. Enter searches; ✨ is an optional action.</p>
      <SearchField label="Search (sample)" placeholder="Search, or describe what you want and tap ✨" value={find} onChange={setFind}
                   action={<SearchAction aria-label="AI search (sample)" disabled={find.trim().length < 3}>✨</SearchAction>} />

      <SectionTitle>Panels</SectionTitle>
      <p className="ui-hint">Every box sits on the one card surface (--card-bg, --card-border, --card-radius, --card-pad).</p>
      <div className="styleguide-grid">
        <Panel title="Plain panel" hint="A hint beside the title">The default box.</Panel>
        <Panel tone="gold" title="🧠 Gold" hint="Games">For games and highlights.</Panel>
        <Panel tone="go" title="Go" hint="Green edge">"Did you make it?" and other yes-moments.</Panel>
        <Panel tone="tile" title="Tile" kicker>Compact, for side rails.</Panel>
      </div>
      <Panel tone="callout" title="Callout" actions={<button type="button" className="btn btn-primary">Do the thing</button>}>
        <p>A big title with its action beside it — the one thing a page wants you to do next.</p>
      </Panel>
      <Prompt question="A question asked in place?" hint="Prompt: a hint, anything to pick, buttons beside it, × to put it away."
              onClose={() => {}}
              actions={<>
                <button type="button" className="btn btn-sm btn-primary">Yes</button>
                <button type="button" className="btn btn-sm">Not now</button>
              </>} />

      <SectionTitle>Text</SectionTitle>
      <p className="ui-note">.ui-note — a muted lead-in under a heading.</p>
      <p className="ui-hint">.ui-hint — small muted help beside or under a control.</p>

      <SectionTitle>People and clubs</SectionTitle>
      <div className="styleguide-row">
        <Avatar user={me} size={24} /><Avatar user={me} size={32} /><Avatar user={me} size={48} />
        <ClubBadge group={shell.group} size={24} /><ClubBadge group={shell.group} size={48} />
      </div>
    </div>
  );
}

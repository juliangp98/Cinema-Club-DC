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
import { SaveStatus, SettingRow, SettingsGroup, SettingsSection, Switch, SwitchRow } from "../ui/Settings";
import SectionMenu from "../ui/SectionMenu";
import StatTiles from "../ui/StatTiles";
import MiniBingo from "../ui/MiniBingo";
import BingoGrid from "../ui/BingoGrid";
import TicketChips from "../ui/TicketChips";
import TicketRow from "../ui/TicketRow";
import Sheet, { SheetTitle } from "../ui/Sheet";
import "./StyleguidePage.css";

// The style guide (R15), for club admins: every piece of the UI kit in one
// place, live, so new features pick from here instead of inventing their own.
// Nothing on it saves anything. Linked from Club → Settings.
const BADGES = [["", "Closed"], ["go", "Going"], ["gold", "Maybe"], ["strong", "Saw it"], ["discord", "via Discord"],
                ["solid", "3 tonight"]];
const SAMPLE_SHOW = { id: 0, start_time: "2099-11-09T21:45:00", end_time: "2099-11-10T00:02:00", purchase_link: null,
                      theatre: { slug: "afi", name: "AFI Silver Theatre" }, format_label: "35mm" };
const SAMPLE_SQUARES = ["🎞️ On film", "🌍 Not in English", "📼 Before 1970", "🌙 Late show", "⭐ Free", "🏛️ A museum",
                        "🎬 A director's debut", "👯 With a friend", "🏠 At home"].map((t, i) => {
  const [emoji, ...label] = t.split(" ");
  return { key: i === 4 ? "free" : `s${i}`, emoji, label: label.join(" "), hint: "What fills it", done: [0, 4, 8].includes(i) };
});

export default function StyleguidePage() {
  const shell = useShell();
  const [seg, setSeg] = useState("ask");
  const [mode, setMode] = useState("never");
  const [on, setOn] = useState(true);
  const [picked, setPicked] = useState(["Agnès Varda", "Wong Kar-wai"]);
  const [find, setFind] = useState("");
  const [sw, setSw] = useState(true);
  const [sw2, setSw2] = useState(false);
  const [tickets, setTickets] = useState(null);
  const [rsvp, setRsvp] = useState(null);
  const [sheet, setSheet] = useState(false);
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

      <SectionTitle>Settings</SectionTitle>
      <p className="ui-hint">Every setting on the site (ui/Settings): a section with a line on what it covers, small group headings,
        rows with the label and hint on the left and the control on the right — a switch for on / off, a segmented choice for three
        ways — saved as they change, with one status line. A whole thing with its own switch (a club's game) is a panel with the
        switch at its head. A page of sections has a section menu (ui/SectionMenu) beside it.</p>
      <div className="ui-split" style={{ "--split-side": "200px" }}>
        <div>
          <SaveStatus status={{ ok: true, text: "Saved" }} />
          <SettingsSection id="sg-settings" title="A section" intro="One line on what these settings cover.">
            <SettingsGroup title="A group">
              <SwitchRow label="An on / off setting" hint="What it does, in a few words." checked={sw} onChange={setSw} />
              <SwitchRow label="Another, off" hint="Off until someone turns it on." checked={sw2} onChange={setSw2} />
              <SettingRow label="A three-way choice" hint="Ask, Always or Never.">
                <Segmented label="Three-way (sample)" options={ASK_ALWAYS_NEVER} value={seg} onChange={v => setSeg(v || "ask")} />
              </SettingRow>
            </SettingsGroup>
          </SettingsSection>
          <Panel as="div" className="game-setting" title="🎱 A game" aside={<Switch label="A game (sample)" checked={sw} onChange={setSw} />}>
            <p className="ui-hint">A setting that's a whole thing: its switch at the head, its options under it.</p>
          </Panel>
        </div>
        <div className="ui-split-side"><SectionMenu label="Sample sections" items={[{ id: "sg-settings", label: "A section" }, { id: "sg-other", label: "Another" }]} /></div>
      </div>

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

      <SectionTitle>Numbers and tables</SectionTitle>
      <p className="ui-hint">StatTiles for numbers at a glance (game records, club totals); .ui-table (in .ui-table-wrap, which
        scrolls on phones) for rows to compare, with a sort button in each heading.</p>
      <StatTiles label="Sample records" items={[{ label: "Trivia", value: "72%", sub: "18 of 25 · best streak 6" },
                                                 { label: "Bingo", value: "2 lines", sub: "1 full card" },
                                                 { label: "Polls", value: 4, sub: "right picks" }]} />
      <div className="ui-table-wrap">
        <table className="ui-table" aria-label="Sample table">
          <thead><tr><th scope="col">Member</th><th scope="col" aria-sort="descending"><button type="button">Trivia ↓</button></th>
            <th scope="col"><button type="button">Polls</button></th></tr></thead>
          <tbody><tr className="me"><td>You</td><td>72%</td><td>4</td></tr><tr><td>A member</td><td>60%</td><td>6</td></tr></tbody>
        </table>
      </div>

      <SectionTitle>Tickets</SectionTitle>
      <p className="ui-hint">TicketChips filter by ticket status (kept in the address); TicketRow is one showing — time, theatre,
        RSVP, tickets, add to calendar. Sold out, or off sale (gone from the theatre's site, likely sold out), still takes RSVPs.</p>
      <TicketChips value={tickets} onChange={setTickets} />
      <TicketRow showtime={{ ...SAMPLE_SHOW, is_sold_out: true, off_sale: true, user_rsvp: rsvp }} apiBase="" onRsvp={(_, v) => setRsvp(v)} />

      <SectionTitle>Bingo</SectionTitle>
      <p className="ui-hint">MiniBingo is a card at a glance (a line gives a gold edge, a full card a double one); BingoGrid is the
        card itself, square by square (compact for someone else's).</p>
      <div className="styleguide-row">
        <MiniBingo cells={[1, 0, 0, 0, 1, 0, 0, 0, 1].map(Boolean)} line size="md" label="A line" />
        <MiniBingo cells={Array(9).fill(true)} full size="md" label="A full card" />
        <MiniBingo cells={[1, 1, 0, 0, 1, 0, 0, 0, 0].map(Boolean)} label="Three of nine" />
      </div>
      <BingoGrid squares={SAMPLE_SQUARES} label="Sample card" compact />

      <SectionTitle>Sheets</SectionTitle>
      <p className="ui-hint">Sheet: a panel over the page for details (a showing, a member's card) — × or Escape closes it.</p>
      <button type="button" className="btn" onClick={() => setSheet(true)}>Open a sheet</button>
      {sheet && (
        <Sheet label="Sample sheet" onClose={() => setSheet(false)}>
          <div className="share-sheet-body">
            <SheetTitle>A sheet</SheetTitle>
            <p className="ui-hint">Its title, then what it's about.</p>
          </div>
        </Sheet>
      )}

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

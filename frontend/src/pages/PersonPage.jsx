import { Link, Navigate, useParams } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import Avatar from "../ui/Avatar";
import Loading from "../ui/Loading";
import TasteChips, { TasteMatch } from "../ui/TasteChips";
import ProfileLists from "../components/ProfileLists";
import useShowtimeSheet from "../shell/useShowtimeSheet";
import { accountLabel } from "../accountLabel";
import { useJson } from "../api";
import { kernelParts } from "../kernels";

const BACK = { to: "/club?tab=members", label: "Members" };

// A member's page (R15 — it was a drawer): who they are, their kernels and
// taste (if they show it), and their lists — Compare first, to plan
// something together. Every member's picture and name leads here; your own
// is the Me page. Only people who share a club with you.
export default function PersonPage({ user, apiBase, groupId }) {
  const id = Number(useParams().id);
  const own = user && id === user.id;
  const { data: person, error } = useJson(own || !id ? null : `${apiBase}/api/users/${id}/profile`);
  const { data: kernels } = useJson(own || !id ? null : `${apiBase}/api/users/${id}/kernels`);
  const { openShowtime, sheet } = useShowtimeSheet({ user, apiBase, groupId });

  if (own) return <Navigate to="/me" replace />;
  if (error || !id) {
    const hidden = error?.status === 403;
    return (
      <div className="page narrow">
        <PageHeader title={hidden ? "Not in your clubs" : "Member not found"} back={BACK} />
        <p className="pv-empty">
          {hidden ? "You can see the members of clubs you're in." : "There's no one here — they may have left."}{" "}
          <Link to="/club?tab=members">See your club's members →</Link>
        </p>
      </div>
    );
  }
  if (!person) return <div className="page narrow"><Loading /></div>;

  const parts = kernels?.breakdown;
  return (
    <div className="page person-page">
      <PageHeader title={person.name} back={BACK}
                  meta={[kernels && { icon: "🍿", label: `${kernels.kernels} kernel${kernels.kernels === 1 ? "" : "s"}`, gold: true }]} />

      <div className="ui-split" style={{ "--split-side": "400px" }}>
      <div className="person-main">
      <section className="me-card">
        <Avatar user={person} size={64} />
        <div className="me-card-text">
          <div className="me-sub">{accountLabel(person)}</div>
          {parts && <small className="profile-kernels-parts">{kernelParts(parts)}</small>}
        </div>
        {person.letterboxd_username && (
          <div className="me-card-actions">
            <a className="btn" href={`https://letterboxd.com/${person.letterboxd_username}`} target="_blank" rel="noreferrer">
              ▤ @{person.letterboxd_username} on Letterboxd ↗
            </a>
          </div>
        )}
      </section>

      <p className="person-bio">{person.bio || <span className="ui-hint">No bio yet.</span>}</p>

      {person.taste && (
        <>
          <SectionTitle>Taste</SectionTitle>
          <TasteMatch match={person.taste_match} />
          <TasteChips taste={person.taste} empty={<p className="ui-hint">Nothing picked yet.</p>} />
        </>
      )}

      </div>
      {/* Wide screens (7f): their lists beside who they are. */}
      <aside className="ui-split-side person-side" aria-label="Their lists">
        <SectionTitle>Lists</SectionTitle>
        <ProfileLists userId={id} apiBase={apiBase} own={false} onOpen={openShowtime} />
      </aside>
      </div>
      {sheet}
    </div>
  );
}

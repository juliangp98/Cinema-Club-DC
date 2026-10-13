import { Link } from "react-router-dom";

// Page titles and section titles: the marquee font with gold double-rule trim.
// `back` ({to, label}) adds a small link above the title for sub-pages;
// `meta` puts the page's at-a-glance facts under it as chips (PageMeta).

export default function PageHeader({ title, meta, actions, back, children }) {
  return (
    <header className="ui-page-header">
      {back && <Link className="ui-page-back" to={back.to}>‹ {back.label}</Link>}
      <div className="ui-page-header-row">
        <h1 className="ui-page-title"><span className="deco">{title}</span></h1>
        {actions && <div className="ui-page-actions">{actions}</div>}
      </div>
      {meta && <PageMeta items={meta} />}
      {children}
    </header>
  );
}

// What a page covers, as a row of chips instead of a sentence (R12): how
// many, which theatres, how far ahead. Each item: {label, icon?, to?, gold?,
// more?, title?, key?} — `to` makes it a link, `more` the row's closing
// "see all →" link — or {node, key} for a ready-made element (a TheatreLink).
// Empty items are skipped.
export function PageMeta({ items, label = "About this page", className = "" }) {
  const shown = (items || []).filter(Boolean);
  if (!shown.length) return null;
  return (
    <ul className={`ui-page-meta ${className}`} aria-label={label}>
      {shown.map((it, i) => {
        if (it.node) return <li key={it.key || i}>{it.node}</li>;
        const body = <>{it.icon && <span aria-hidden="true">{it.icon} </span>}{it.label}</>;
        const cls = it.more ? "ui-page-meta-more" : `chip${it.gold ? " gold" : ""}`;
        return (
          <li key={it.key || i}>
            {it.to ? <Link className={cls} to={it.to} title={it.title}>{body}</Link>
              : <span className={cls} title={it.title}>{body}</span>}
          </li>
        );
      })}
    </ul>
  );
}

// A section's heading. `link` ({to, label}, or {onClick, label}) is the gold
// "See all →"-style link at its end; `action` anything else there.
export function SectionTitle({ children, action, link }) {
  const end = link
    ? (link.to ? <Link className="ui-section-link" to={link.to}>{link.label}</Link>
      : <button type="button" className="ui-section-link" onClick={link.onClick}>{link.label}</button>)
    : action;
  return (
    <div className="ui-section-title">
      <h2><span className="deco">{children}</span></h2>
      <span className="ui-section-rule" aria-hidden="true" />
      {end}
    </div>
  );
}

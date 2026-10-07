import { Link } from "react-router-dom";

// Page titles and section titles: the marquee font with gold double-rule trim.
// `back` ({to, label}) adds a small link above the title for sub-pages.

export default function PageHeader({ title, subtitle, actions, back, children }) {
  return (
    <header className="ui-page-header">
      {back && <Link className="ui-page-back" to={back.to}>‹ {back.label}</Link>}
      <div className="ui-page-header-row">
        <h1 className="ui-page-title"><span className="deco">{title}</span></h1>
        {actions && <div className="ui-page-actions">{actions}</div>}
      </div>
      {subtitle && <p className="ui-page-subtitle">{subtitle}</p>}
      {children}
    </header>
  );
}

export function SectionTitle({ children, action }) {
  return (
    <div className="ui-section-title">
      <h2><span className="deco">{children}</span></h2>
      <span className="ui-section-rule" aria-hidden="true" />
      {action}
    </div>
  );
}

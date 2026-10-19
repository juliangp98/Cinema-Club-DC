import { Fragment } from "react";
import { Link } from "react-router-dom";
import { LINK, hrefOf, isOutside } from "../help";

// Help's text with its links (7f): "[Club settings → Games](club-settings-games)"
// becomes a link straight there (where the arrival glow lights it). An
// unknown reference — say, from an AI answer — stays plain words. A place
// outside the site opens in a new tab.
export default function RichText({ text, onNavigate }) {
  const out = [];
  let last = 0;
  for (const m of (text || "").matchAll(LINK)) {
    out.push(text.slice(last, m.index));
    const to = hrefOf(m[2]);
    out.push(!to ? <Fragment key={m.index}>{m[1]}</Fragment>
      : isOutside(to) ? <a key={m.index} href={to} className="rich-link" target="_blank" rel="noopener noreferrer">{m[1]} ↗</a>
      : <Link key={m.index} to={to} className="rich-link" onClick={onNavigate}>{m[1]}</Link>);
    last = m.index + m[0].length;
  }
  out.push(text?.slice(last) || "");
  return <>{out}</>;
}

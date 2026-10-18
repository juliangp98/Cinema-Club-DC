import { Fragment } from "react";
import { Link } from "react-router-dom";
import { LINK, hrefOf } from "../help";

// Help's text with its links (7f): "[Club settings → Games](club-settings-games)"
// becomes a link straight there (where the arrival glow lights it). An
// unknown reference — say, from an AI answer — stays plain words.
export default function RichText({ text, onNavigate }) {
  const out = [];
  let last = 0;
  for (const m of (text || "").matchAll(LINK)) {
    out.push(text.slice(last, m.index));
    const to = hrefOf(m[2]);
    out.push(to ? <Link key={m.index} to={to} className="rich-link" onClick={onNavigate}>{m[1]}</Link>
      : <Fragment key={m.index}>{m[1]}</Fragment>);
    last = m.index + m[0].length;
  }
  out.push(text?.slice(last) || "");
  return <>{out}</>;
}

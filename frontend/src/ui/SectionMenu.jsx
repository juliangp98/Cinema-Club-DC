import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

// A page's section menu (7f/7g): Help's topics, Club settings, your Settings.
// Chips on phones, a list in the side column on wide screens (.ui-split-side);
// the section you're in is the selected (gold) one as you scroll, and a jump
// to a section lands at its top without the arrival glow — it's navigation,
// not a "look here". `items`: [{id, label}].
export default function SectionMenu({ items, label }) {
  const { search, hash } = useLocation();
  const [current, setCurrent] = useState(items[0]?.id);
  useEffect(() => {
    const box = document.querySelector(".shell-main") || window;
    const top = () => (box.getBoundingClientRect ? box.getBoundingClientRect().top : 0);
    const spy = () => {
      let on = items[0]?.id;
      for (const it of items) {
        const el = document.getElementById(it.id);
        if (el && el.getBoundingClientRect().top - top() <= 120) on = it.id;
      }
      setCurrent(on);
    };
    spy();
    box.addEventListener("scroll", spy, { passive: true });
    return () => box.removeEventListener("scroll", spy);
  }, [items.map(i => i.id).join()]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (hash.length > 1 && items.some(i => `#${i.id}` === hash)) setCurrent(hash.slice(1)); }, [hash]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <nav className="section-menu" aria-label={label}>
      <ul>
        {items.map(it => (
          <li key={it.id}>
            <Link to={{ search, hash: `#${it.id}` }} state={{ arrive: "quiet" }} aria-current={current === it.id ? "true" : undefined}
                  className={`chip${current === it.id ? " gold" : ""}`} onClick={() => setCurrent(it.id)}>{it.label}</Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

import { useEffect } from "react";
import { useLocation } from "react-router-dom";

// Scroll to the #anchor in the address once the page has drawn it (`ready`):
// Help's topics, a theatre's For you shelf.
export default function useHashScroll(ready = true) {
  const { hash } = useLocation();
  useEffect(() => {
    if (!hash || !ready) return undefined;
    const t = setTimeout(() => document.getElementById(decodeURIComponent(hash.slice(1)))?.scrollIntoView({ block: "start" }), 100);
    return () => clearTimeout(t);
  }, [hash, ready]);
}

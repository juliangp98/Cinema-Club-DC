import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

// The one overlay panel: slides in from the right on desktop, up from the
// bottom on phones (with a handle you can drag down to close). Escape, the
// close button, or a click on the backdrop close it; the page behind doesn't
// scroll while it's open. Sheets can stack (a screening opened from the
// activity panel); Escape closes only the top one.
const openSheets = [];

export default function Sheet({ onClose, label, children, className = "" }) {
  const panelRef = useRef(null);
  const drag = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  // Registered once per open sheet (callers often pass a new onClose each render).
  useEffect(() => {
    const me = {};
    openSheets.push(me);
    function onKey(e) {
      if (e.key === "Escape" && !e.defaultPrevented && openSheets[openSheets.length - 1] === me) {
        e.preventDefault();
        closeRef.current();
      }
    }
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const prevFocus = document.activeElement;
    panelRef.current?.focus({ preventScroll: true });
    return () => {
      openSheets.splice(openSheets.indexOf(me), 1);
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      prevFocus?.focus?.({ preventScroll: true });
    };
  }, []);

  // Drag the handle down (phones) to dismiss.
  function onPointerDown(e) {
    drag.current = { y: e.clientY, dy: 0 };
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function onPointerMove(e) {
    if (!drag.current) return;
    drag.current.dy = Math.max(0, e.clientY - drag.current.y);
    if (panelRef.current) panelRef.current.style.transform = `translateY(${drag.current.dy}px)`;
  }
  function onPointerUp() {
    if (!drag.current) return;
    const { dy } = drag.current;
    drag.current = null;
    if (dy > 90) onClose();
    else if (panelRef.current) panelRef.current.style.transform = "";
  }

  return createPortal(
    <div className="ui-sheet-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        ref={panelRef}
        className={`ui-sheet ${className}`}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        tabIndex={-1}
      >
        <div
          className="ui-sheet-handle"
          aria-hidden="true"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        />
        <button type="button" className="ui-sheet-close" onClick={onClose} aria-label="Close">&times;</button>
        {children}
      </div>
    </div>,
    document.body,
  );
}

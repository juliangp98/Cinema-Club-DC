import { useState, useEffect, useRef, useId } from "react";

// The one dropdown: a trigger button and a panel of items. Closes on outside
// click, Escape, or choosing an item; arrow keys move between items.
//   <Menu label="Group" trigger={<>Club ▾</>}>
//     <MenuItem onSelect={...}>Members</MenuItem>
//   </Menu>
export default function Menu({ trigger, label, align = "end", className = "", triggerClassName = "", children }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return;
    function onDown(e) { if (ref.current && !ref.current.contains(e.target)) setOpen(false); }
    function onKey(e) {
      if (e.key === "Escape") { setOpen(false); ref.current?.querySelector(".ui-menu-trigger")?.focus(); }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        const items = [...(ref.current?.querySelectorAll(".ui-menu-item:not(:disabled)") || [])];
        if (!items.length) return;
        e.preventDefault();
        const i = items.indexOf(document.activeElement);
        const next = e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
        items[next].focus();
      }
    }
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className={`ui-menu ${className}`} ref={ref}>
      <button
        type="button"
        className={`ui-menu-trigger ${triggerClassName}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={label}
        onClick={() => setOpen(o => !o)}
      >
        {trigger}
      </button>
      {open && (
        <div id={panelId} role="menu" className={`ui-menu-panel align-${align}`} onClick={e => {
          if (e.target.closest(".ui-menu-item")) setOpen(false);
        }}>
          {children}
        </div>
      )}
    </div>
  );
}

export function MenuItem({ onSelect, active = false, danger = false, children, ...rest }) {
  return (
    <button
      type="button"
      role="menuitem"
      className={`ui-menu-item${active ? " active" : ""}${danger ? " danger" : ""}`}
      onClick={onSelect}
      {...rest}
    >
      {children}
    </button>
  );
}

export function MenuLabel({ children }) {
  return <div className="ui-menu-label">{children}</div>;
}

export function MenuDivider() {
  return <div className="ui-menu-divider" role="separator" />;
}

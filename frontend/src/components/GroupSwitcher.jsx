import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";

export default function GroupSwitcher({ apiBase, activeGroupId, setGroupId }) {
  const [groups, setGroups] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const navigate = useNavigate();

  useEffect(() => {
    fetchGroups();
  }, [apiBase]);

  async function fetchGroups() {
    try {
      const r = await fetch(`${apiBase}/api/groups`, { credentials: "include" });
      if (r.ok) setGroups(await r.json());
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    function onClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    function onKey(e) { if (e.key === "Escape") setOpen(false); }
    if (open) {
      window.addEventListener("mousedown", onClick);
      window.addEventListener("keydown", onKey);
    }
    return () => {
      window.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const activeGroup = groups.find(g => g.id === activeGroupId);

  return (
    <div className="group-switcher" ref={ref}>
      <button className="group-switcher-btn" onClick={() => setOpen(!open)}>
        {activeGroup ? activeGroup.name : "Select Group"}
        <span className="group-switcher-caret">{open ? "\u25B4" : "\u25BE"}</span>
      </button>

      {open && (
        <div className="group-dropdown">
          {groups.map(g => (
            <button
              key={g.id}
              className={`group-dropdown-item${g.id === activeGroupId ? " active" : ""}`}
              onClick={() => { setGroupId(g.id); setOpen(false); }}
            >
              <span className="group-dropdown-name">{g.name}</span>
              {g.role === "admin" && <span className="group-role-badge">admin</span>}
            </button>
          ))}
          <div className="group-dropdown-actions">
            {activeGroup && (
              <>
                <button
                  className="group-dropdown-action"
                  onClick={() => { setOpen(false); navigate("/members"); }}
                >
                  Members
                </button>
                <button
                  className="group-dropdown-action"
                  onClick={() => { setOpen(false); navigate("/polls"); }}
                >
                  Polls
                </button>
              </>
            )}
            <button
              className="group-dropdown-action"
              onClick={() => { setOpen(false); navigate("/groups"); }}
            >
              Browse
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

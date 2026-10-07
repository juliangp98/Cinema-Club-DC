import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import Menu, { MenuItem, MenuLabel, MenuDivider } from "../ui/Menu";
import { UsersIcon, TrophyIcon, CompassIcon } from "../ui/icons";

// The group pill in the top bar: switch groups, and reach the group's pages.
export default function GroupSwitcher({ apiBase, activeGroupId, setGroupId }) {
  const [groups, setGroups] = useState([]);
  const navigate = useNavigate();

  useEffect(() => {
    fetch(`${apiBase}/api/groups`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : []))
      .then(setGroups)
      .catch(() => {});
  }, [apiBase, activeGroupId]);

  const active = groups.find(g => g.id === activeGroupId);

  return (
    <Menu
      label="Switch group"
      className="topbar-groupmenu"
      triggerClassName="topbar-group"
      trigger={<><span className="topbar-group-name">{active ? active.name : "Choose a group"}</span>
                 <span className="caret">▾</span></>}
    >
      {groups.length > 0 && <MenuLabel>Your groups</MenuLabel>}
      {groups.map(g => (
        <MenuItem key={g.id} active={g.id === activeGroupId} onSelect={() => setGroupId(g.id)}>
          <span style={{ flex: 1 }}>{g.name}</span>
          {g.role === "admin" && <span className="chip">admin</span>}
        </MenuItem>
      ))}
      {active && (
        <>
          <MenuDivider />
          <MenuItem onSelect={() => navigate("/members")}><UsersIcon /> Members</MenuItem>
          <MenuItem onSelect={() => navigate("/leaderboard")}><TrophyIcon /> Leaderboard</MenuItem>
        </>
      )}
      <MenuItem onSelect={() => navigate("/groups")}><CompassIcon /> Browse groups</MenuItem>
    </Menu>
  );
}

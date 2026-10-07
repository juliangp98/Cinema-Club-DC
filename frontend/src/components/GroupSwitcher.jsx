import { useNavigate } from "react-router-dom";
import Menu, { MenuItem, MenuLabel, MenuDivider } from "../ui/Menu";
import { ClubBadge, shortNameOf } from "../ui/Avatar";
import { UsersIcon, CompassIcon } from "../ui/icons";

// The club pill in the top bar: the club's picture and name — the full name
// on wide screens, its short name (or initials) when space is tight — and a
// menu to switch clubs or open the club's page.
export default function GroupSwitcher({ groups, activeGroupId, setGroupId }) {
  const navigate = useNavigate();
  const active = groups.find(g => g.id === activeGroupId);

  return (
    <Menu
      label={active ? `${active.name}: switch club` : "Switch club"}
      className="topbar-groupmenu"
      triggerClassName="topbar-group"
      trigger={<>
        {active && (
          <span className={`topbar-group-badge${active.photo_url || active.emoji ? "" : " initials"}`}>
            <ClubBadge group={active} size={24} />
          </span>
        )}
        <span className="topbar-group-name" title={active?.name}>{active ? active.name : "Choose a club"}</span>
        <span className="topbar-group-short" title={active?.name}>{active ? shortNameOf(active) : "Club"}</span>
        <span className="caret">▾</span>
      </>}
    >
      {active && <MenuLabel>{active.name}</MenuLabel>}
      {active && <MenuItem onSelect={() => navigate("/club")}><UsersIcon /> Club page</MenuItem>}
      {groups.length > 1 && (
        <>
          <MenuDivider />
          <MenuLabel>Switch club</MenuLabel>
          {groups.map(g => (
            <MenuItem key={g.id} active={g.id === activeGroupId} onSelect={() => setGroupId(g.id)}>
              <ClubBadge group={g} size={22} />
              <span style={{ flex: 1 }}>{g.name}</span>
              {g.role === "admin" && <span className="chip">admin</span>}
            </MenuItem>
          ))}
        </>
      )}
      <MenuDivider />
      <MenuItem onSelect={() => navigate("/groups")}><CompassIcon /> Find or start a club</MenuItem>
    </Menu>
  );
}

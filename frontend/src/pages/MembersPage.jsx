import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import GroupMembers from "../components/GroupMembers";
import ProfileMenu from "../components/ProfileMenu";
import UserProfileDrawer from "../components/UserProfileDrawer";

export default function MembersPage({ user, setUser, apiBase, activeGroupId }) {
  const navigate = useNavigate();
  const [group, setGroup] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showProfile, setShowProfile] = useState(false);
  const [profileUserId, setProfileUserId] = useState(null);

  // Fetch active group info
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!activeGroupId) { setLoading(false); return; }
    fetch(`${apiBase}/api/groups`, { credentials: "include" })
      .then(r => r.ok ? r.json() : [])
      .then(groups => {
        const g = groups.find(g => g.id === activeGroupId);
        setGroup(g || null);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [activeGroupId, apiBase]);

  function handleProfileUpdate(updatedUser) {
    setUser(updatedUser);
  }

  function logout() {
    fetch(`${apiBase}/api/logout`, { method: "POST", credentials: "include" })
      .then(() => window.location.reload());
  }

  if (loading) return null;
  if (!group) {
    navigate("/");
    return null;
  }

  return (
    <div className="group-discovery-page">
      <div className="group-discovery-container">
        <header className="group-discovery-header">
          <button className="group-back-btn" onClick={() => navigate("/")}>
            &larr; Groups
          </button>
          <h1 className="group-discovery-title">Members</h1>
          <div style={{ marginLeft: "auto", position: "relative" }}>
            <div
              className="user-avatar"
              style={{ background: user.avatar_color, color: "#0d0c09" }}
              title={`${user.name} — ${user.email}`}
              onClick={() => setShowProfile(!showProfile)}
            >
              {user.name.slice(0, 2).toUpperCase()}
            </div>
            {showProfile && (
              <ProfileMenu
                user={user}
                apiBase={apiBase}
                onUpdate={handleProfileUpdate}
                onLogout={logout}
                onClose={() => setShowProfile(false)}
              />
            )}
          </div>
        </header>

        <GroupMembers
          group={group}
          apiBase={apiBase}
          onClose={() => navigate("/")}
          onViewProfile={setProfileUserId}
          embedded
        />
      </div>

      {profileUserId && (
        <UserProfileDrawer
          userId={profileUserId}
          apiBase={apiBase}
          onClose={() => setProfileUserId(null)}
        />
      )}
    </div>
  );
}

import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import GroupMembers from "../components/GroupMembers";
import UserProfileDrawer from "../components/UserProfileDrawer";
import PageHeader from "../ui/PageHeader";

export default function MembersPage({ user, setUser, apiBase, activeGroupId }) {
  const navigate = useNavigate();
  const [group, setGroup] = useState(null);
  const [loading, setLoading] = useState(true);
  const [params, setParams] = useSearchParams();
  // ?profile=me (the "My lists" menu item) or ?profile=<id> opens that profile.
  const [profileUserId, setProfileUserId] = useState(() => {
    const p = params.get("profile");
    return p === "me" ? user.id : (parseInt(p, 10) || null);
  });

  useEffect(() => {
    if (params.has("profile")) setParams({}, { replace: true });
  }, [params, setParams]);

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



  if (loading) return null;
  if (!group) {
    navigate("/");
    return null;
  }

  return (
    <div className="group-discovery-page">
      <div className="group-discovery-container">
        <PageHeader title="Members" />

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
          viewerId={user.id}
          apiBase={apiBase}
          onClose={() => setProfileUserId(null)}
        />
      )}
    </div>
  );
}

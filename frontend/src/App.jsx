import { useState, useEffect, useCallback } from "react";
import { BrowserRouter, Routes, Route, Navigate, useParams, useNavigate } from "react-router-dom";
import Calendar from "./pages/Calendar";
import Login from "./pages/Login";
import GroupDiscovery from "./pages/GroupDiscovery";

const API_BASE = import.meta.env.VITE_API_BASE || "";

function AuthGuard({ user, loading, children, apiBase, onLogin }) {
  const params = useParams();

  if (loading) {
    return (
      <div className="loading-screen">
        <span className="marquee-text">CINEMA CLUB DC</span>
      </div>
    );
  }

  // If on invite route and not logged in, show invite acceptance
  if (!user && params.token) {
    return <Login onLogin={onLogin} apiBase={apiBase} inviteToken={params.token} />;
  }

  if (!user) {
    return <Login onLogin={onLogin} apiBase={apiBase} />;
  }

  return children;
}

// Wrapper that redirects to /groups if user has no groups
function CalendarOrRedirect({ user, setUser, apiBase, groupId, setGroupId, hasGroups }) {
  const navigate = useNavigate();

  useEffect(() => {
    if (user && !hasGroups) {
      navigate("/groups", { replace: true });
    }
  }, [user, hasGroups, navigate]);

  if (!groupId) {
    return (
      <div className="app-shell">
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh", gap: "1rem" }}>
          <h2 style={{ color: "var(--gold)" }}>Welcome to Cinema Club DC!</h2>
          <p style={{ color: "var(--muted)" }}>Join a group to see showtimes and RSVP with friends.</p>
          <button
            className="auth-btn"
            style={{ width: "auto", padding: "0.75rem 2rem" }}
            onClick={() => navigate("/groups")}
          >
            FIND A GROUP
          </button>
        </div>
      </div>
    );
  }

  return (
    <Calendar
      user={user}
      setUser={setUser}
      apiBase={apiBase}
      groupId={groupId}
      setGroupId={setGroupId}
    />
  );
}

export default function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hasGroups, setHasGroups] = useState(true); // assume true until proven otherwise
  const [activeGroupId, setActiveGroupId] = useState(() => {
    const stored = localStorage.getItem("cinemaclub_group_id");
    return stored ? parseInt(stored, 10) : null;
  });

  const fetchGroups = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/groups`, { credentials: "include" });
      if (r.ok) {
        const groups = await r.json();
        setHasGroups(groups.length > 0);
        const stored = localStorage.getItem("cinemaclub_group_id");
        const storedId = stored ? parseInt(stored, 10) : null;
        const validIds = groups.map(g => g.id);
        if (storedId && validIds.includes(storedId)) {
          setActiveGroupId(storedId);
        } else if (groups.length > 0) {
          setActiveGroupId(groups[0].id);
          localStorage.setItem("cinemaclub_group_id", String(groups[0].id));
        } else {
          setActiveGroupId(null);
          localStorage.removeItem("cinemaclub_group_id");
        }
      }
    } catch {
      // ignore
    }
  }, []);

  const fetchUser = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/api/auth/me`, { credentials: "include" });
      const d = await r.json();
      setUser(d.user || null);
      if (d.user) {
        await fetchGroups();
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [fetchGroups]);

  useEffect(() => { fetchUser(); }, [fetchUser]);

  function handleLogin(u) {
    setUser(u);
    fetchGroups();
  }

  function handleSetGroupId(id) {
    setActiveGroupId(id);
    setHasGroups(true);
    localStorage.setItem("cinemaclub_group_id", String(id));
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route
          path="/"
          element={
            <AuthGuard user={user} loading={loading} apiBase={API_BASE} onLogin={handleLogin}>
              <CalendarOrRedirect
                user={user}
                setUser={setUser}
                apiBase={API_BASE}
                groupId={activeGroupId}
                setGroupId={handleSetGroupId}
                hasGroups={hasGroups}
              />
            </AuthGuard>
          }
        />
        <Route
          path="/invite/:token"
          element={
            <AuthGuard user={user} loading={loading} apiBase={API_BASE} onLogin={handleLogin}>
              <Navigate to="/" replace />
            </AuthGuard>
          }
        />
        <Route
          path="/groups"
          element={
            <AuthGuard user={user} loading={loading} apiBase={API_BASE} onLogin={handleLogin}>
              <GroupDiscovery
                user={user}
                setUser={setUser}
                apiBase={API_BASE}
                activeGroupId={activeGroupId}
                setGroupId={handleSetGroupId}
              />
            </AuthGuard>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

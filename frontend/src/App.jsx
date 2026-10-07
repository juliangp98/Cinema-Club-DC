import { useState, useEffect, useCallback } from "react";
import { BrowserRouter, Routes, Route, Navigate, useParams, useNavigate } from "react-router-dom";
import Calendar from "./pages/Calendar";
import Login from "./pages/Login";
import GroupDiscovery from "./pages/GroupDiscovery";
import MembersPage from "./pages/MembersPage";
import PollsPage from "./pages/PollsPage";
import PollDetailPage from "./pages/PollDetailPage";
import LeaderboardPage from "./pages/LeaderboardPage";
import VerifySignin from "./pages/VerifySignin";
import MePage from "./pages/MePage";
import FilmPage from "./pages/FilmPage";
import DiscoverPage from "./pages/DiscoverPage";
import BrowsePage from "./pages/BrowsePage";
import AppShell from "./shell/AppShell";

const API_BASE = import.meta.env.VITE_API_BASE || "";

// Results of "Sign in with Discord" / "Connect Discord", passed back by the
// backend as ?discord=… or ?discord_error=…
const DISCORD_NOTICES = {
  connected: "Discord connected — anything you did in Discord is now part of this account.",
  expired: "That Discord sign-in expired — please try again.",
  cancelled: "Discord sign-in was cancelled.",
  failed: "Couldn't reach Discord — please try again.",
  taken: "That Discord account is already connected to a different Cinema Club account.",
  inactive: "That account has been deactivated.",
  unavailable: "Discord sign-in isn't set up on this site yet.",
  signed_out: "Sign in first, then connect Discord from your profile menu.",
};

function readDiscordNotice() {
  const params = new URLSearchParams(window.location.search);
  const error = params.get("discord_error");
  const key = error || (params.get("discord") === "connected" ? "connected" : null);
  if (!key) return null;
  return { text: DISCORD_NOTICES[key] || "Discord sign-in didn't work — please try again.", error: !!error };
}

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

// Group pages (Discover, Calendar…): redirect to /groups if the user has no groups.
function GroupGate({ user, groupId, hasGroups, children }) {
  const navigate = useNavigate();

  useEffect(() => {
    if (user && !hasGroups) {
      navigate("/groups", { replace: true });
    }
  }, [user, hasGroups, navigate]);

  if (!groupId) {
    return (
      <div className="page narrow">
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "60vh", gap: "1rem", textAlign: "center" }}>
          <h2 className="deco center" style={{ color: "var(--amber)", fontSize: "1.8rem", fontWeight: 400 }}>Welcome to Cinema Club DC</h2>
          <p style={{ color: "var(--muted)" }}>Join a group to see showtimes and RSVP with friends.</p>
          <button className="btn btn-primary" onClick={() => navigate("/groups")}>
            Find a group
          </button>
        </div>
      </div>
    );
  }

  return children;
}

export default function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hasGroups, setHasGroups] = useState(true); // assume true until proven otherwise
  const [activeGroupId, setActiveGroupId] = useState(() => {
    const stored = localStorage.getItem("cinemaclub_group_id");
    return stored ? parseInt(stored, 10) : null;
  });
  const [notice, setNotice] = useState(readDiscordNotice);
  // Back from "Sign in with Discord" as signed in: if the browser didn't keep
  // the session, say so instead of silently showing the sign-in page again.
  const [fromDiscord] = useState(() => new URLSearchParams(window.location.search).get("discord") === "signed_in");

  // Drop the ?discord… result params once read, keeping any others (?showtime=).
  useEffect(() => {
    const url = new URL(window.location.href);
    if (!url.searchParams.has("discord") && !url.searchParams.has("discord_error")) return;
    url.searchParams.delete("discord");
    url.searchParams.delete("discord_error");
    window.history.replaceState(null, "", url.pathname + url.search + url.hash);
  }, []);

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
      if (!d.user && fromDiscord) {
        setNotice({ error: true, text: "Discord signed you in, but this browser didn't keep the sign-in. "
          + "Try once more, or use the email link below." });
      }
      if (d.user) {
        await fetchGroups();
      }
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [fetchGroups, fromDiscord]);

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
      {notice && (
        <div className={`site-notice${notice.error ? " error" : ""}`} role="status">
          <span>{notice.text}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)}>&times;</button>
        </div>
      )}
      <Routes>
        {/* Emailed sign-in links land here; deliberately outside AuthGuard. */}
        <Route
          path="/auth/verify"
          element={<VerifySignin apiBase={API_BASE} onLogin={handleLogin} />}
        />
        <Route
          path="/invite/:token"
          element={
            <AuthGuard user={user} loading={loading} apiBase={API_BASE} onLogin={handleLogin}>
              <Navigate to="/" replace />
            </AuthGuard>
          }
        />
        {/* Every signed-in page shares the app shell (top bar, phone tab bar). */}
        <Route
          element={
            <AuthGuard user={user} loading={loading} apiBase={API_BASE} onLogin={handleLogin}>
              <AppShell user={user} setUser={setUser} apiBase={API_BASE}
                        groupId={activeGroupId} setGroupId={handleSetGroupId} />
            </AuthGuard>
          }
        >
          <Route
            path="/"
            element={
              <GroupGate user={user} groupId={activeGroupId} hasGroups={hasGroups}>
                <DiscoverPage user={user} apiBase={API_BASE} groupId={activeGroupId} />
              </GroupGate>
            }
          />
          <Route
            path="/calendar"
            element={
              <GroupGate user={user} groupId={activeGroupId} hasGroups={hasGroups}>
                <Calendar user={user} setUser={setUser} apiBase={API_BASE}
                          groupId={activeGroupId} setGroupId={handleSetGroupId} />
              </GroupGate>
            }
          />
          <Route
            path="/films/:id"
            element={
              <GroupGate user={user} groupId={activeGroupId} hasGroups={hasGroups}>
                <FilmPage user={user} apiBase={API_BASE} groupId={activeGroupId} />
              </GroupGate>
            }
          />
          {/* Discover is home now; old /discover links land there too. */}
          <Route path="/discover" element={<Navigate to="/" replace />} />
          <Route
            path="/browse"
            element={
              <GroupGate user={user} groupId={activeGroupId} hasGroups={hasGroups}>
                <BrowsePage apiBase={API_BASE} groupId={activeGroupId} />
              </GroupGate>
            }
          />
          <Route path="/me" element={<MePage user={user} apiBase={API_BASE} groupId={activeGroupId} />} />
          <Route
            path="/groups"
            element={<GroupDiscovery user={user} setUser={setUser} apiBase={API_BASE}
                                     activeGroupId={activeGroupId} setGroupId={handleSetGroupId} />}
          />
          <Route
            path="/members"
            element={<MembersPage user={user} setUser={setUser} apiBase={API_BASE} activeGroupId={activeGroupId} />}
          />
          <Route
            path="/polls"
            element={<PollsPage user={user} setUser={setUser} apiBase={API_BASE}
                                activeGroupId={activeGroupId} setGroupId={handleSetGroupId} />}
          />
          <Route
            path="/leaderboard"
            element={<LeaderboardPage user={user} setUser={setUser} apiBase={API_BASE} activeGroupId={activeGroupId} />}
          />
          <Route
            path="/polls/:pollId"
            element={<PollDetailPage user={user} setUser={setUser} apiBase={API_BASE} />}
          />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

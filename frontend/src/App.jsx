import { useState, useEffect, useCallback, Suspense } from "react";
import PageLoading from "./ui/Loading";
import { BrowserRouter, Routes, Route, Navigate, useParams, useLocation, useSearchParams } from "react-router-dom";
import DiscoverPage from "./pages/DiscoverPage";       // home: in the main bundle
import lazyPage from "./lazyPage";

// Every other page loads when first visited (R9e).
const Calendar = lazyPage(() => import("./pages/Calendar"));
const Login = lazyPage(() => import("./pages/Login"));
const GroupDiscovery = lazyPage(() => import("./pages/GroupDiscovery"));
const ClubPage = lazyPage(() => import("./pages/ClubPage"));
const PollDetailPage = lazyPage(() => import("./pages/PollDetailPage"));
const PollEditorPage = lazyPage(() => import("./pages/PollEditorPage"));
const VerifySignin = lazyPage(() => import("./pages/VerifySignin"));
const MePage = lazyPage(() => import("./pages/MePage"));
const FilmPage = lazyPage(() => import("./pages/FilmPage"));
const BrowsePage = lazyPage(() => import("./pages/BrowsePage"));
const FeedPage = lazyPage(() => import("./pages/FeedPage"));
const PlayPage = lazyPage(() => import("./pages/PlayPage"));
const HelpPage = lazyPage(() => import("./pages/HelpPage"));
const TheatresPage = lazyPage(() => import("./pages/Theatres"), "TheatresPage");
const TheatrePage = lazyPage(() => import("./pages/Theatres"), "TheatrePage");
const SpotlightsPage = lazyPage(() => import("./pages/DiscoverMore"), "SpotlightsPage");
const DoublesPage = lazyPage(() => import("./pages/DiscoverMore"), "DoublesPage");
const StyleguidePage = lazyPage(() => import("./pages/StyleguidePage"));
const PersonPage = lazyPage(() => import("./pages/PersonPage"));
import AppShell from "./shell/AppShell";
import { rememberNext, safeNext } from "./afterSignIn";
import { clearCache, getJson } from "./api";

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

function Loading() {
  return (
    <div className="loading-screen">
      <span className="marquee-text">CINEMA CLUB DC</span>
    </div>
  );
}

// The sign-in page (/signin?next=…): back to where you were once signed in.
function SignIn({ user, onLogin, apiBase }) {
  const [params] = useSearchParams();
  const target = safeNext(params.get("next")) || "/";
  if (user && !user.is_guest) return <Navigate to={target} replace />;
  rememberNext(target);
  // A guest here is keeping their profile: signing up or in brings it along.
  return <Login onLogin={onLogin} apiBase={apiBase} next={target} keeping={!!user?.is_guest} />;
}

// Invite links: accept on sign-in, then home.
function InviteRoute({ user, onLogin, apiBase }) {
  const params = useParams();
  if (user) return <Navigate to="/" replace />;
  return <Login onLogin={onLogin} apiBase={apiBase} inviteToken={params.token} />;
}

// Pages that need an account (your profile, a club's polls / members / board).
function RequireSignIn({ user, children }) {
  const location = useLocation();
  if (!user) return <Navigate to={`/signin?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  return children;
}

export default function App() {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [hasGroups, setHasGroups] = useState(true); // assume true until proven otherwise
  const [groups, setGroups] = useState([]);          // yours, each with your role (R5c)
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
      const groups = await getJson(`${API_BASE}/api/groups`, { cache: false });
      setHasGroups(groups.length > 0);
      setGroups(groups);
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
    } catch {
      // ignore
    }
  }, []);

  const fetchUser = useCallback(async () => {
    try {
      const d = await getJson(`${API_BASE}/api/auth/me`, { cache: false });
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
    clearCache();                     // pages reload as this account
    setUser(u);
    fetchGroups();
  }

  // Public pages run in club mode only for a signed-in member of a club —
  // never for a guest (whatever club this browser last remembered).
  const scopeGroupId = user && !user.is_guest && hasGroups ? activeGroupId : null;
  const scopeGroup = groups.find(g => g.id === scopeGroupId) || null;   // its role decides what you can do

  function handleSetGroupId(id) {
    setActiveGroupId(id);
    setHasGroups(true);
    localStorage.setItem("cinemaclub_group_id", String(id));
    fetchGroups();                  // a club just joined or made: pick up your role there
  }

  return (
    <BrowserRouter>
      {notice && (
        <div className={`site-notice${notice.error ? " error" : ""}`} role="status">
          <span>{notice.text}</span>
          <button type="button" aria-label="Dismiss" onClick={() => setNotice(null)}>&times;</button>
        </div>
      )}
      {loading ? <Loading /> : (
      <Suspense fallback={<div className="page"><PageLoading /></div>}>
      <Routes>
        {/* Emailed sign-in links land here. */}
        <Route path="/auth/verify" element={<VerifySignin apiBase={API_BASE} onLogin={handleLogin} />} />
        <Route path="/signin" element={<SignIn user={user} onLogin={handleLogin} apiBase={API_BASE} />} />
        <Route path="/invite/:token" element={<InviteRoute user={user} onLogin={handleLogin} apiBase={API_BASE} />} />
        {/* Every page shares the app shell; what's playing is public (R5a). */}
        <Route element={<AppShell user={user} setUser={setUser} apiBase={API_BASE} groupId={scopeGroupId} group={scopeGroup}
                                  groups={groups} setGroupId={handleSetGroupId} refreshGroups={fetchGroups} />}>
          <Route path="/" element={<DiscoverPage user={user} apiBase={API_BASE} groupId={scopeGroupId} />} />
          <Route path="/calendar" element={<Calendar user={user} apiBase={API_BASE} groupId={scopeGroupId} />} />
          <Route path="/films/:id" element={<FilmPage user={user} apiBase={API_BASE} groupId={scopeGroupId} />} />
          {/* Discover is home now; old /discover links land there too. */}
          <Route path="/discover" element={<Navigate to="/" replace />} />
          <Route path="/discover/spotlights" element={<SpotlightsPage apiBase={API_BASE} groupId={scopeGroupId} />} />
          <Route path="/discover/doubles" element={<DoublesPage apiBase={API_BASE} groupId={scopeGroupId} />} />
          <Route path="/browse" element={<BrowsePage apiBase={API_BASE} groupId={scopeGroupId} user={user} />} />
          <Route path="/theatres" element={<TheatresPage apiBase={API_BASE} />} />
          <Route path="/theatres/:slug" element={<TheatrePage apiBase={API_BASE} groupId={scopeGroupId} />} />
          <Route path="/me" element={<RequireSignIn user={user}><MePage user={user} apiBase={API_BASE} groupId={scopeGroupId} /></RequireSignIn>} />
          <Route path="/groups" element={
            <RequireSignIn user={user}>
              <GroupDiscovery user={user} setUser={setUser} apiBase={API_BASE} activeGroupId={activeGroupId} setGroupId={handleSetGroupId} />
            </RequireSignIn>} />
          <Route path="/feed" element={
            <RequireSignIn user={user}><FeedPage user={user} apiBase={API_BASE} groupId={scopeGroupId} /></RequireSignIn>} />
          <Route path="/help" element={<HelpPage apiBase={API_BASE} />} />
          <Route path="/people/:id" element={
            <RequireSignIn user={user}><PersonPage user={user} apiBase={API_BASE} groupId={scopeGroupId} /></RequireSignIn>} />
          <Route path="/styleguide" element={<RequireSignIn user={user}><StyleguidePage /></RequireSignIn>} />
          <Route path="/play" element={
            <RequireSignIn user={user}><PlayPage user={user} apiBase={API_BASE} groupId={scopeGroupId} /></RequireSignIn>} />
          <Route path="/club" element={
            <RequireSignIn user={user}><ClubPage user={user} apiBase={API_BASE} /></RequireSignIn>} />
          {/* The Club page has the old Members and Leaderboard pages as tabs (R6b). */}
          <Route path="/members" element={<Navigate to="/club?tab=members" replace />} />
          <Route path="/leaderboard" element={<Navigate to="/club?tab=leaderboard" replace />} />
          {/* Polls live on Play (R15). */}
          <Route path="/polls" element={<Navigate to="/play#polls" replace />} />
          <Route path="/polls/new" element={
            <RequireSignIn user={user}><PollEditorPage apiBase={API_BASE} activeGroupId={scopeGroupId} /></RequireSignIn>} />
          <Route path="/polls/:pollId" element={
            <RequireSignIn user={user}><PollDetailPage user={user} setUser={setUser} apiBase={API_BASE} /></RequireSignIn>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
      )}
    </BrowserRouter>
  );
}

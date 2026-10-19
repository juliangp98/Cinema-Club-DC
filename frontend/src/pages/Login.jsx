import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getJson, send } from "../api";
import { SITE_NAME } from "../site";

// `keeping`: a guest is keeping their profile (R5b) — signing up turns it into
// the account; signing in (or Discord) brings their plans to the account they have.
export default function Login({ onLogin, apiBase, inviteToken, next, keeping = false }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState(keeping ? "signup" : "login"); // "login" | "signup"
  const [sentTo, setSentTo] = useState("");  // address a sign-in link was emailed to
  const [discordEnabled, setDiscordEnabled] = useState(false);

  const isInvite = !!inviteToken;

  useEffect(() => {
    getJson(`${apiBase}/api/auth/providers`)
      .then(d => setDiscordEnabled(!!d?.discord))
      .catch(() => {});
  }, [apiBase]);

  // Login and signup both email a one-time link; the session starts when it's
  // opened (see VerifySignin). Returns true when the link was sent.
  async function requestLink() {
    setLoading(true);
    setError("");
    const path = mode === "signup" ? "/api/auth/signup" : "/api/auth/login";
    const body = { email: email.trim().toLowerCase() };
    if (mode === "signup") body.name = name.trim();
    try {
      const d = await send(`${apiBase}${path}`, "POST", body);
      setSentTo(d.email || body.email);
      return true;
    } catch (e) {
      setError(e.status ? e.data?.error || "Something went wrong" : "Could not connect to server");
      return false;
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(e) {
    e.preventDefault();
    if (mode === "signup" && !name.trim()) {
      setError("Please enter your name");
      return;
    }
    requestLink();
  }

  async function handleAcceptInvite(e) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Please enter your name");
      return;
    }
    setLoading(true);
    setError("");
    try {
      onLogin((await send(`${apiBase}/api/auth/accept-invite`, "POST", { token: inviteToken, name: name.trim() })).user);
    } catch (e) {
      setError(e.status ? e.data?.error || "Could not accept invite" : "Could not connect to server");
    } finally {
      setLoading(false);
    }
  }

  function switchMode(next) {
    setMode(next);
    setError("");
  }

  if (sentTo) {
    return (
      <div className="auth-page">
        <div className="auth-box">
          <span className="auth-logo">{SITE_NAME.toUpperCase()}</span>
          <p className="auth-subtitle">Check Your Email</p>
          <p className="auth-note">
            We sent a {mode === "signup" ? "confirmation" : "sign-in"} link to <strong>{sentTo}</strong>.
            It works once and expires in 15 minutes.
          </p>
          {error && <div className="auth-error">{error}</div>}
          <button className="btn btn-primary btn-block btn-lg" type="button" onClick={requestLink} disabled={loading}>
            {loading ? "..." : "Resend link"}
          </button>
          <p className="auth-toggle">
            <button type="button" className="linkish" onClick={() => { setSentTo(""); setError(""); }}>
              Use a different email
            </button>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="auth-page">
      <div className="auth-box">
        <span className="auth-logo">{SITE_NAME.toUpperCase()}</span>
        <p className="auth-subtitle">
          {isInvite ? "You've Been Invited" : keeping ? "Keep Your Profile" : mode === "signup" ? "Create Your Account" : "Private Cinema Schedule"}
        </p>
        {keeping && !isInvite && (
          <p className="auth-note">
            Your plans, watchlist and reactions come with you. New here? Sign up. Already have an account? Sign in and
            they'll be added to it.
          </p>
        )}

        {isInvite ? (
          <form onSubmit={handleAcceptInvite}>
            {error && <div className="auth-error">{error}</div>}
            <label className="auth-label">Your Name</label>
            <input
              className="auth-input"
              type="text"
              placeholder="Your display name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              autoFocus
            />
            <button className="btn btn-primary btn-block btn-lg" type="submit" disabled={loading}>
              {loading ? "..." : "JOIN"}
            </button>
          </form>
        ) : (
          <form onSubmit={handleSubmit}>
            {error && <div className="auth-error">{error}</div>}
            <label className="auth-label">Your Email</label>
            <input
              className="auth-input"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
            {mode === "signup" && (
              <>
                <label className="auth-label">Your Name</label>
                <input
                  className="auth-input"
                  type="text"
                  placeholder="Display name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  required
                />
              </>
            )}
            <button className="btn btn-primary btn-block btn-lg" type="submit" disabled={loading}>
              {loading ? "..." : "Email me a link"}
            </button>
            {discordEnabled && (
              <>
                <div className="auth-or">or</div>
                {/* Signs in, or creates an account for Discord members — no separate sign-up. */}
                <a className="btn btn-discord btn-block btn-lg" href={`${apiBase}/api/auth/discord/start${next && next !== "/" ? `?next=${encodeURIComponent(next)}` : ""}`}>
                  Sign in with Discord
                </a>
              </>
            )}
            <p className="auth-toggle">
              {mode === "signup" ? "Already have an account? " : "New here? "}
              <button
                type="button"
                className="linkish"
                onClick={() => switchMode(mode === "signup" ? "login" : "signup")}
              >
                {mode === "signup" ? "Log in" : "Sign up"}
              </button>
            </p>
          </form>
        )}
        {/* What's playing is open to everyone (R5a). */}
        {!inviteToken && <Link className="auth-browse" to="/">{keeping ? "‹ Not now" : "‹ Keep browsing without signing in"}</Link>}
      </div>
    </div>
  );
}

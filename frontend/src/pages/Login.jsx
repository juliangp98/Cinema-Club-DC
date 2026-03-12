import { useState } from "react";

export default function Login({ onLogin, apiBase, inviteToken }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState("login"); // "login" | "signup"

  const isInvite = !!inviteToken;

  async function handleLogin(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });
      const d = await r.json();
      if (!r.ok) {
        setError(d.error || "Login failed");
      } else {
        onLogin(d.user);
      }
    } catch {
      setError("Could not connect to server");
    } finally {
      setLoading(false);
    }
  }

  async function handleSignup(e) {
    e.preventDefault();
    if (!name.trim()) {
      setError("Please enter your name");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/api/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: email.trim().toLowerCase(), name: name.trim() }),
      });
      const d = await r.json();
      if (!r.ok) {
        setError(d.error || "Signup failed");
      } else {
        onLogin(d.user);
      }
    } catch {
      setError("Could not connect to server");
    } finally {
      setLoading(false);
    }
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
      const r = await fetch(`${apiBase}/api/auth/accept-invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ token: inviteToken, name: name.trim() }),
      });
      const d = await r.json();
      if (!r.ok) {
        setError(d.error || "Could not accept invite");
      } else {
        onLogin(d.user);
      }
    } catch {
      setError("Could not connect to server");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-box">
        <span className="auth-logo">CINEMA CLUB DC</span>
        <p className="auth-subtitle">
          {isInvite ? "You've Been Invited" : mode === "signup" ? "Create Your Account" : "Private Cinema Schedule"}
        </p>

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
            <button className="auth-btn" type="submit" disabled={loading}>
              {loading ? "..." : "JOIN"}
            </button>
          </form>
        ) : mode === "signup" ? (
          <form onSubmit={handleSignup}>
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
            <label className="auth-label">Your Name</label>
            <input
              className="auth-input"
              type="text"
              placeholder="Display name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <button className="auth-btn" type="submit" disabled={loading}>
              {loading ? "..." : "SIGN UP"}
            </button>
            <p className="auth-toggle">
              Already have an account?{" "}
              <button type="button" className="auth-toggle-btn" onClick={() => { setMode("login"); setError(""); }}>
                Log in
              </button>
            </p>
          </form>
        ) : (
          <form onSubmit={handleLogin}>
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
            <button className="auth-btn" type="submit" disabled={loading}>
              {loading ? "..." : "ENTER"}
            </button>
            <p className="auth-toggle">
              New here?{" "}
              <button type="button" className="auth-toggle-btn" onClick={() => { setMode("signup"); setError(""); }}>
                Sign up
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}

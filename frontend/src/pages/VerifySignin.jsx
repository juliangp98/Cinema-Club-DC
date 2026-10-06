import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

// Landing page for emailed sign-in links (/auth/verify?token=...). The token is
// redeemed on an explicit click rather than on page load: some mail providers
// open links in advance to scan them, which would use up a one-time link
// before the person ever sees it.
export default function VerifySignin({ apiBase, onLogin }) {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const navigate = useNavigate();
  const [error, setError] = useState(token ? "" : "This link is missing its sign-in code. Request a new one.");
  const [loading, setLoading] = useState(false);

  async function handleContinue() {
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/api/auth/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ token }),
      });
      const d = await r.json();
      if (!r.ok) {
        setError(d.error || "Could not sign you in");
        return;
      }
      onLogin(d.user);
      navigate("/", { replace: true });
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
        <p className="auth-subtitle">Sign In</p>
        {error ? (
          <>
            <div className="auth-error">{error}</div>
            <button className="auth-btn" type="button" onClick={() => navigate("/", { replace: true })}>
              BACK TO SIGN IN
            </button>
          </>
        ) : (
          <>
            <p className="auth-note">You're one step away. Continue to finish signing in on this device.</p>
            <button className="auth-btn" type="button" onClick={handleContinue} disabled={loading} autoFocus>
              {loading ? "..." : "CONTINUE"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

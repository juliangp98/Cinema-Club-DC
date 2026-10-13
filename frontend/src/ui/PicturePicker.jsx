import { useRef, useState } from "react";
import { send } from "../api";

const QUICK = ["🎬", "🍿", "🎞️", "🎥", "📽️", "🎟️", "🌙", "👻", "🦇", "🌹", "🐈‍⬛", "⭐"];

// Choose a picture (R6b): upload a photo, pick an emoji, or go back to
// initials. Used for your profile and (by admins) for a club. `extra` adds
// more choices (e.g. "Use my Discord picture").
export default function PicturePicker({ preview, onUpload, onEmoji, onClear, clearLabel = "Use initials",
                                        canUpload = true, uploadNote, extra }) {
  const file = useRef(null);
  const [emoji, setEmoji] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (fn) => {
    setBusy(true);
    setError("");
    try { await fn(); } catch (e) { setError(e.message || "Couldn't save that — try again."); } finally { setBusy(false); }
  };
  return (
    <div className="picture-picker">
      <div className="picture-picker-row">
        {preview}
        <div className="picture-picker-actions">
          {canUpload && (
            <>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => file.current?.click()}>
                {busy ? "Saving…" : "Upload a photo"}
              </button>
              <input ref={file} type="file" accept="image/jpeg,image/png,image/webp,image/gif" hidden
                     onChange={e => { const f = e.target.files?.[0]; e.target.value = ""; if (f) run(() => onUpload(f)); }} />
            </>
          )}
          {extra}
          {onClear && <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => run(onClear)}>{clearLabel}</button>}
        </div>
      </div>
      <div className="picture-picker-emoji" role="group" aria-label="Or pick an emoji">
        {QUICK.map(e => (
          <button key={e} type="button" className="picture-emoji" disabled={busy} onClick={() => run(() => onEmoji(e))}
                  aria-label={`Use ${e}`}>{e}</button>
        ))}
        <form className="picture-emoji-own" onSubmit={ev => { ev.preventDefault(); if (emoji.trim()) run(() => onEmoji(emoji.trim())); }}>
          <input className="share-input" value={emoji} maxLength={16} onChange={e => setEmoji(e.target.value)}
                 placeholder="Any emoji" aria-label="Any emoji" />
          <button type="submit" className="btn btn-sm" disabled={busy || !emoji.trim()}>Use</button>
        </form>
      </div>
      <p className="picture-picker-note">{uploadNote || "Photos: JPEG, PNG, WebP or GIF up to 5 MB. They're cropped square, and location details are removed."}</p>
      {error && <p className="share-error">{error}</p>}
    </div>
  );
}

// Upload a picture (throws the server's message, like send()).
export function sendPicture(url, file) {
  const body = new FormData();
  body.append("file", file);
  return send(url, "POST", body);
}

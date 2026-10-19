import Panel from "./Panel";

// A question asked in place (R15) — "Want to hear when…?", "Share in
// Discord?", "Mention you in the digest?" — always the same small card: the
// question, a hint, anything to pick, buttons beside it (full width on
// phones), and × at the far end to put it away.
export default function Prompt({ question, hint, actions, onClose, label, className = "", children }) {
  const close = onClose && <button type="button" className="ui-prompt-close" aria-label="Not now" onClick={onClose}>×</button>;
  return (
    <Panel as="div" tone="prompt" role="group" aria-label={label || question} className={className} title={question}
           actions={(actions || close) && <>{actions}{close}</>}>
      {hint && <p className="ui-hint">{hint}</p>}
      {children}
    </Panel>
  );
}

// The one bordered box (R12) — games, prompts and callouts all use it, so
// they look and space alike:
//   tone      "gold" (games), "go" (green edge: "Did you make it?"),
//             "callout" (gold edge, big title, actions beside it),
//             "tile" (compact, for side-rail summaries)
//   title     the heading (`titleId` labels the section); `kicker` makes it
//             the small uppercase kind
//   hint      a muted line beside the title
//   aside     something at the head's far end (e.g. a close button)
//   actions   buttons: under the content, or beside it for a callout
export default function Panel({ as: Tag = "section", tone, title, titleId, kicker, hint, aside, actions,
                                className = "", children, ...rest }) {
  const cls = ["ui-panel", tone && `ui-panel-${tone}`, className].filter(Boolean).join(" ");
  const head = (title || hint || aside) && (
    <div className="ui-panel-head">
      {title && (
        <strong id={titleId} className={`ui-panel-title${kicker ? " kicker" : ""}${tone === "callout" ? " deco" : ""}`}>
          {title}
        </strong>
      )}
      {hint && <span className="ui-hint">{hint}</span>}
      {aside && <span className="ui-panel-aside">{aside}</span>}
    </div>
  );
  return (
    <Tag className={cls} {...rest}>
      {tone === "callout" ? <div className="ui-panel-body">{head}{children}</div> : <>{head}{children}</>}
      {actions && <div className="ui-panel-actions">{actions}</div>}
    </Tag>
  );
}

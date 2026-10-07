// Club roles (R5c): each includes the ones before it. Admins grant and revoke them.
export const ROLES = [
  { value: "viewer", label: "Read-only", hint: "Sees the club; can't RSVP, vote or comment" },
  { value: "member", label: "Member", hint: "RSVP, vote, comment, react, share" },
  { value: "organizer", label: "Organizer", hint: "Member + runs polls and posts them to Discord" },
  { value: "admin", label: "Admin", hint: "Organizer + members, invites, roles, settings" },
];
export const roleLabel = role => ROLES.find(r => r.value === role)?.label || "Member";

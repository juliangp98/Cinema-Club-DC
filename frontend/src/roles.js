// Club roles (R5c): each includes the ones before it. Admins grant and revoke them.
export const ROLES = [
  { value: "viewer", label: "Read-only", hint: "Sees the club; can't RSVP, vote or comment" },
  { value: "member", label: "Member", hint: "RSVP, vote, comment, react, share" },
  { value: "organizer", label: "Organizer", hint: "Member + runs polls, the club's theatres and games, and join requests" },
  { value: "admin", label: "Admin", hint: "Organizer + the club's details, invites, roles and members" },
];
export const roleLabel = role => ROLES.find(r => r.value === role)?.label || "Member";
// Runs the club day to day (R15): polls, theatres, games, join requests.
export const runsClub = role => role === "organizer" || role === "admin";

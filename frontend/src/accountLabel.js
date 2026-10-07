// The line shown under a member's name: their email, or for Discord-only
// accounts (made through the bot or "Sign in with Discord" — no email) their
// Discord handle.
export function accountLabel(user) {
  if (!user) return "";
  if (user.is_guest) return "Guest profile · only in this browser";
  if (user.email) return user.email;
  if (user.discord_username) return `@${user.discord_username} on Discord`;
  // Other members' emails are hidden unless you're a club admin.
  return user.discord_only ? "Discord member" : "";
}

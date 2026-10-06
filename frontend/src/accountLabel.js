// The line shown under a member's name: their email, or for Discord-only
// accounts (made through the bot or "Sign in with Discord" — no email) their
// Discord handle.
export function accountLabel(user) {
  if (!user) return "";
  if (user.email) return user.email;
  return user.discord_username ? `@${user.discord_username} on Discord` : "Discord member";
}

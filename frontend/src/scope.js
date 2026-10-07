// Club mode or public mode (R5a): schedule requests carry ?group_id only when
// you're signed in and in a club; without it the server answers in public
// mode (every tracked theatre, no member data).
export const groupParam = groupId => (groupId ? `group_id=${groupId}&` : "");

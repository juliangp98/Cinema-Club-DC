import { useState, useCallback } from "react";
import ShowtimeDrawer from "../components/ShowtimeDrawer";
import { groupParam } from "../scope";
import { getJson, rsvp, attend } from "../api";

// Open any screening's drawer from a page that doesn't otherwise manage
// showtimes: const { openShowtime, sheet } = useShowtimeSheet(...); render {sheet}.
export default function useShowtimeSheet({ user, apiBase, groupId, onChange }) {
  const [selected, setSelected] = useState(null);

  const openShowtime = useCallback((id) => {
    getJson(`${apiBase}/api/showtimes/${id}?${groupParam(groupId)}`)
      .then(data => { if (data) setSelected([data]); })
      .catch(() => {});
  }, [apiBase, groupId]);

  const patch = (id, fields) => setSelected(prev => (prev ? prev.map(s => (s.id === id ? { ...s, ...fields } : s)) : prev));

  async function onRsvp(showtimeId, status) {
    const d = await rsvp(apiBase, showtimeId, status, groupId).catch(() => null);
    if (d) { patch(showtimeId, d); onChange?.(); }
  }

  async function onAttendance(showtimeId, status) {
    if (!(await attend(apiBase, showtimeId, status).catch(() => null))) return false;
    patch(showtimeId, { user_attendance: status });
    onChange?.();
    return true;
  }

  const sheet = selected ? (
    <ShowtimeDrawer showtimes={selected} user={user} groupId={groupId} apiBase={apiBase}
                    onClose={() => setSelected(null)} onRsvp={onRsvp} onAttendance={onAttendance} />
  ) : null;
  return { openShowtime, sheet };
}

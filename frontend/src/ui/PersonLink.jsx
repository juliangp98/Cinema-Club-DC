import { Link } from "react-router-dom";

// A member's page (R15): /people/<id> — every picture and name of a member
// leads there (Avatar's `link`, or this for a name). Yours is the Me page.
export const personPath = id => `/people/${id}`;

export default function PersonLink({ user, className = "", children }) {
  if (!user?.id) return <span className={className}>{children ?? user?.name}</span>;
  return <Link className={`person-link ${className}`.trim()} to={personPath(user.id)}>{children ?? user.name}</Link>;
}

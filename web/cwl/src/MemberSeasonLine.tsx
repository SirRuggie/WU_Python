import { memberSignupsOpen } from "./memberSeason";
import type { Season } from "./api";

export default function MemberSeasonLine({
  season,
  hideClosedStatus = false,
}: {
  season: Season;
  hideClosedStatus?: boolean;
}) {
  const close = Date.parse(season.signup_deadline || "");
  const open = memberSignupsOpen(season);
  const date = Number.isFinite(close)
    ? new Date(close).toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
      })
    : null;
  return (
    <p className="member-season-line">
      <strong>{season.label}</strong>
      {open ? " · Signups open" : hideClosedStatus ? "" : " · Signups closed"}
      {open && date ? ` · closes ${date}` : ""}
    </p>
  );
}

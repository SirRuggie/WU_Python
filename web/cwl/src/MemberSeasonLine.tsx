import type { Season } from "./api";

export default function MemberSeasonLine({ season }: { season: Season }) {
  const close = Date.parse(season.signup_deadline || "");
  const open = season.signup_open;
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
      <strong>{season.label}</strong> · {open ? "Open" : "Signups closed"}
      {open && date ? ` · closes ${date}` : ""}
    </p>
  );
}

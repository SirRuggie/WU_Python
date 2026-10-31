import { useEffect, useState } from "react";
import { TriangleAlert } from "lucide-react";
import type { Season } from "./api";
import "./MemberSignupStatus.css";

type Signed = {
  tag: string;
  player_name?: string;
  pool: string;
  assigned_clan_tag?: string | null;
};
type Linked = { tag: string; name: string };
export function relativeMinutes(at: number, now: number) {
  const minutes = Math.max(1, Math.ceil((at - now) / 60000));
  if (minutes >= 1440) {
    const days = Math.round(minutes / 1440);
    return `in ${days} day${days === 1 ? "" : "s"}`;
  }
  if (minutes >= 60) return `in ${Math.ceil(minutes / 60)} h`;
  return `in ${minutes} min`;
}
function formatMemberDate(at: number) {
  return new Date(at).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
function signupCloseLine(season: Season | undefined, now: number) {
  const at = Date.parse(season?.signup_deadline || "");
  return Number.isFinite(at)
    ? `Signups close ${formatMemberDate(at)}${at > now ? ` · ${relativeMinutes(at, now)}` : ""}`
    : null;
}
export function memberDateLines(
  season: Season | undefined,
  published: boolean,
  now: number,
): string[] {
  if (!season?.signup_deadline || !season.placements_by || published) return [];
  const deadline = Date.parse(season.signup_deadline),
    placement = Date.parse(season.placements_by);
  if (!Number.isFinite(deadline) || !Number.isFinite(placement)) return [];
  if (placement < now)
    return ["Taking a little longer than usual · check back soon"];
  if (season.signup_open && season.status === "draft")
    return [
      signupCloseLine(season, now)!,
      `You'll see your clan by ${formatMemberDate(placement)}.`,
    ];
  return [
    `Signups closed · you'll see your clan by ${formatMemberDate(placement)} · ${relativeMinutes(placement, now)}`,
  ];
}
export function signupHeading(signed: number, total: number | null) {
  if (total === null)
    return `✓ You're signed up · ${signed} account${signed === 1 ? "" : "s"}`;
  return signed === total
    ? `✓ You're signed up · all ${total} account${total === 1 ? "" : "s"}`
    : `✓ You're signed up · ${signed} of ${total} accounts`;
}
export default function MemberSignupStatus({
  signups,
  accounts,
  season,
  published = false,
  onChange,
  onRemaining,
  onRefresh,
  savedView = false,
  publicationUnavailable = false,
  onAssignments,
}: {
  signups: Signed[];
  accounts: Linked[] | null;
  season?: Season;
  published?: boolean;
  onChange?: () => void;
  onRemaining: () => void;
  onRefresh?: () => void;
  savedView?: boolean;
  publicationUnavailable?: boolean;
  onAssignments?: () => void;
}) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000);
    return () => clearInterval(timer);
  }, []);
  const remaining =
    accounts?.filter((a) => !signups.some((s) => s.tag === a.tag)) || [];
  const total = accounts
    ? new Set([...accounts, ...signups].map((a) => a.tag)).size
    : null;
  const open = season?.signup_open && season.status === "draft";
  const waiting = signups.filter((s) => !s.assigned_clan_tag);
  const partial =
    published &&
    waiting.length > 0 &&
    waiting.length < signups.length &&
    !savedView;
  const dateLines = memberDateLines(season, published, now);
  const signupDeadlineLine = signupCloseLine(season, now);
  return (
    <div className="member-signup-summary">
      <section
        className={
          signups.length ? "member-signup-success" : "member-signup-empty"
        }
      >
        <h2>
          {signups.length
            ? partial
              ? "✓ You're signed up · waiting for your clan"
              : signupHeading(signups.length, total)
            : "You haven't signed up any accounts yet."}
        </h2>
        {signups.length > 0 && (
          <p>
            {publicationUnavailable ? (
              <>
                Clan assignments could not be checked.{" "}
                <a
                  href="/assignments"
                  onClick={(event) => {
                    if (onAssignments) {
                      event.preventDefault();
                      onAssignments();
                    }
                  }}
                >
                  My clan ›
                </a>
              </>
            ) : published && !waiting.length ? (
              onAssignments ? (
                <a
                  href="/assignments"
                  onClick={(event) => {
                    event.preventDefault();
                    onAssignments();
                  }}
                >
                  Your published clan assignments are ready to view.
                </a>
              ) : (
                "Your published clan assignments are ready to view."
              )
            ) : (
              "We've got your signup. Your clan will show here once staff finish the roster."
            )}
          </p>
        )}
        {signups.length > 0 && (
          <ul>
            {(partial ? waiting : signups).map((s) => (
              <li key={s.tag}>
                {s.player_name || s.tag} ·{" "}
                {s.pool === "main" ? "Main CWL" : "Lazy CWL"}
              </li>
            ))}
          </ul>
        )}
        {dateLines.map((line) => (
          <p className="member-signup-date" key={line}>
            {line}
          </p>
        ))}
        {open && signups.length > 0 && !savedView && onChange && (
          <button onClick={onChange}>Change signups ›</button>
        )}
        {!signups.length &&
          (open ? (
            <button onClick={onRemaining}>Sign up for CWL ›</button>
          ) : (
            <p>Signups are closed.</p>
          ))}
        {onRefresh && (
          <button className="member-signup-refresh" onClick={onRefresh}>
            Refresh
          </button>
        )}
      </section>
      {open && signups.length > 0 && remaining.length > 0 && (
        <section className="member-signup-remaining">
          <h2>
            <TriangleAlert aria-hidden="true" size={22} />
            {remaining.length} account{remaining.length === 1 ? "" : "s"} not
            signed up yet
          </h2>
          {signupDeadlineLine && (
            <p className="member-signup-date">{signupDeadlineLine}</p>
          )}
          <button onClick={onRemaining}>
            Sign up {remaining.length} more account
            {remaining.length === 1 ? "" : "s"} ›
          </button>
        </section>
      )}
    </div>
  );
}

import { comparisonAge, sameLocationClan } from "./comparisonLocation";
import { MapPin } from "lucide-react";

type Location = {
  current_clan_tag?: string | null;
  current_clan_name?: string | null;
  current_clan_checked_at?: string | null;
};
export function playerClanStatus(
  assignedTag: string | null,
  assignedName: string,
  location: Location,
  now: number,
  checking = false,
) {
  const currentClanKnown = Number.isFinite(
    Date.parse(location.current_clan_checked_at || ""),
  );
  const sameClan =
    !!assignedTag && sameLocationClan(location, assignedTag, assignedName);
  const inClan = !!(currentClanKnown && sameClan);
  const name = assignedTag ? assignedName : "Not assigned";
  const current =
    location.current_clan_name ||
    location.current_clan_tag ||
    (assignedTag ? "No clan" : "in no clan");
  const age = comparisonAge(location.current_clan_checked_at || undefined, now);
  const minutes = Math.max(
    0,
    Math.floor(
      (now - Date.parse(location.current_clan_checked_at || "")) / 60000,
    ),
  );
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  const spokenAge =
    minutes === 0
      ? "just now"
      : [
          hours ? `${hours} hour${hours === 1 ? "" : "s"}` : "",
          remainder ? `${remainder} minute${remainder === 1 ? "" : "s"}` : "",
        ]
          .filter(Boolean)
          .join(" ") + " ago";
  const suffix = !currentClanKnown
    ? `· ${checking ? "Checking…" : "location not checked yet"}`
    : inClan
      ? `In clan · ${age}`
      : `Now in ${current === "in no clan" ? "no clan" : current} · ${age}`;
  const description =
    `Assigned clan: ${name}.` +
    (!currentClanKnown
      ? checking
        ? " Checking location."
        : " Location not checked yet."
      : ` ${inClan ? "In clan" : `Now in ${current === "in no clan" || current === "No clan" ? "no clan" : current}`}, checked ${spokenAge}.`);
  return {
    currentClanKnown,
    checking,
    inClan,
    name,
    current,
    age,
    suffix,
    description,
    assigned: !!assignedTag,
  };
}
export default function PlayerClanStatus({
  status,
  className = "",
  id,
  showAssigned = true,
  currentOnly = false,
}: {
  status: ReturnType<typeof playerClanStatus>;
  className?: string;
  id?: string;
  showAssigned?: boolean;
  currentOnly?: boolean;
}) {
  return (
    <span id={id} className={`player-clan-status ${className}`}>
      <span
        className={`roster-player-placement${status.inClan ? " is-in-clan" : status.assigned && status.currentClanKnown ? " is-elsewhere" : ""}${!status.assigned ? " is-unassigned" : ""}${status.checking && !status.currentClanKnown ? " is-checking" : ""}`}
        title={`${status.name} ${status.suffix}`}
        aria-hidden="true"
      >
        {showAssigned && <strong>{status.name}</strong>}
        {status.inClan && !currentOnly && (
          <span className="player-in-clan-pill">In clan</span>
        )}
        <span className="roster-player-current" title={status.suffix}>
          {!status.currentClanKnown ? (
            status.suffix
          ) : status.inClan && !currentOnly ? (
            `· ${status.age}`
          ) : (
            <>
              <MapPin
                className="player-location-pin"
                size={14}
                aria-label="Now in"
              />{" "}
              <span
                className={
                  status.assigned && !status.inClan
                    ? "player-current-clan is-elsewhere"
                    : "player-current-clan"
                }
              >
                {status.current}
              </span>{" "}
              · {status.age}
            </>
          )}
        </span>
      </span>
      <span className="sr-only">{status.description}</span>
    </span>
  );
}

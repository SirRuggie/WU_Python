import { comparisonAge } from "./comparisonLocation";

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
    assignedTag &&
    (location.current_clan_tag
      ? location.current_clan_tag === assignedTag
      : !!location.current_clan_name &&
        location.current_clan_name === assignedName);
  const inClan = !!(currentClanKnown && sameClan);
  const name = assignedTag ? assignedName : "Not assigned";
  const current =
    location.current_clan_name || location.current_clan_tag || "in no clan";
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
      : `→ ${current} · ${age}`;
  const description =
    `Assigned clan: ${name}.` +
    (!currentClanKnown
      ? " Location not checked yet."
      : ` ${inClan ? "In clan" : `Now in ${current === "in no clan" ? "no clan" : current}`}, checked ${spokenAge}.`);
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
}: {
  status: ReturnType<typeof playerClanStatus>;
  className?: string;
  id?: string;
}) {
  return (
    <span id={id} className={`player-clan-status ${className}`}>
      <span
        className={`roster-player-placement${status.inClan ? " is-in-clan" : status.assigned && status.currentClanKnown ? " is-elsewhere" : ""}${!status.assigned ? " is-unassigned" : ""}${status.checking && !status.currentClanKnown ? " is-checking" : ""}`}
        title={`${status.name} ${status.suffix}`}
        aria-hidden="true"
      >
        <strong>{status.name}</strong>
        {status.inClan && <span className="player-in-clan-pill">In clan</span>}
        <span className="roster-player-current" title={status.suffix}>
          {!status.currentClanKnown ? (
            status.suffix
          ) : status.inClan ? (
            `· ${status.age}`
          ) : (
            <>
              →{" "}
              <span
                className={
                  status.assigned
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

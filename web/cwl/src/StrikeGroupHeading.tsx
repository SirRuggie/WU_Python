import DiscordIdentity, { type DiscordProfile } from "./DiscordIdentity";
import { strikeCountLabel } from "./strikeCountLabel";
import type { ActivityGroupKey } from "./strikeActivityGroups";
import type { ActivityAccount } from "./strikeActivityView";

/** Clan or Discord heading for a run of rows: name, account count, active strikes. */
export default function StrikeGroupHeading({
  head,
  rows,
  profiles,
  resolving,
}: {
  head: ActivityGroupKey;
  rows: ActivityAccount[];
  profiles: Record<string, DiscordProfile>;
  resolving: boolean;
}) {
  const strikes = rows.reduce((total, row) => total + row.active_strikes, 0);
  return (
    <header className="strike-group-heading">
      {head.kind === "discord" ? (
        <DiscordIdentity
          userId={head.discordId}
          displayName={head.label}
          resolvedMember={profiles[head.discordId!] || null}
          resolving={resolving}
          contact={false}
          username={false}
        />
      ) : (
        <strong>{head.label}</strong>
      )}
      <small>
        {strikeCountLabel(rows.length, "account")}
        {head.kind !== "clan" &&
          ` · ${strikeCountLabel(strikes, "active strike")}`}
      </small>
    </header>
  );
}

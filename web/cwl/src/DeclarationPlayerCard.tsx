import type { StaffDetailsRequest } from "./staffDetailsRequest";
import type { RosterAccount } from "./roster";
import type { ComparisonLocation } from "./comparisonLocation";
import PlayerClanStatus, { playerClanStatus } from "./PlayerClanStatus";
import PlayerCardMeta from "./PlayerCardMeta";
import TownHallIcon from "./TownHallIcon";
import StaffPlayerButton from "./StaffPlayerButton";
import DiscordContact from "./DiscordContact";
import "./PlayerCard.css";
export default function DeclarationPlayerCard({
  account,
  clanName,
  record,
  now,
  request,
  highlighted,
}: {
  account: RosterAccount;
  clanName: string;
  record?: ComparisonLocation;
  now: number;
  request: Omit<StaffDetailsRequest, "tag">;
  highlighted?: boolean;
}) {
  const status = playerClanStatus(
    account.assigned_clan_tag,
    clanName,
    record || {},
    now,
    true,
  );
  return (
    <article
      className={`player-card player-card-compact declaration-player compare-account-${status.inClan ? "arrived" : "missing"}${highlighted ? " is-match" : ""}`}
    >
      <div className="declaration-player-top">
        <StaffPlayerButton {...request} tag={account.tag}>
          <span className="player-card-inline-th" aria-hidden="true">
            <TownHallIcon level={account.town_hall} />
          </span>
          <span className="player-card-name-text">{account.player_name}</span>
        </StaffPlayerButton>
        {!status.inClan && (
          <DiscordContact
            userId={account.user_id}
            compact
            className="declaration-dm"
          />
        )}
      </div>
      <PlayerCardMeta account={account} showPool={false} />
      <PlayerClanStatus status={status} />
      {!!record?.current_clan_tag && record.outside_family && (
        <span className="compare-tag is-warning">Outside family</span>
      )}
    </article>
  );
}

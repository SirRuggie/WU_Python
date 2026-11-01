import { useId } from "react";
import { ownerTimeZone } from "./compareTimeZone";
import "./PlayerCard.css";
import PlayerClanStatus, { playerClanStatus } from "./PlayerClanStatus";
import TownHallIcon from "./TownHallIcon";
import PlayerCardMeta from "./PlayerCardMeta";
import type { RosterAccount, RosterClan } from "./roster";
import RosterAccountMenu from "./RosterAccountMenu";
import {
  comparisonLocation,
  type ComparisonLocation,
} from "./comparisonLocation";
import {
  comparisonPublishNote,
  outsideComparisonRange,
} from "./comparePresentation";
import { compactRosterWeight } from "./rosterCompactWeight";
import type { PublishedComparisonAccount } from "./useComparisonLocations";

type Props = {
  account: RosterAccount;
  ownerNickname?: string;
  ownerTimeZone?: import("./compareTimeZone").OwnerTimeZone;
  clan: RosterClan;
  record?: ComparisonLocation;
  now: number;
  published: PublishedComparisonAccount[] | null;
  busy: boolean;
  onDetails: () => void;
};
export default function ComparePlayerCard({
  account,
  ownerNickname,
  ownerTimeZone: savedZone,
  clan,
  record,
  now,
  published,
  busy,
  onDetails,
}: Props) {
  const id = useId();
  const zone = ownerTimeZone(ownerNickname, savedZone);
  const location = comparisonLocation(record, clan.tag, now, clan.name);
  const status = playerClanStatus(
    clan.tag,
    clan.name || clan.tag,
    record || {},
    now,
    true,
  );
  const outsideRange = outsideComparisonRange(account.effective_weight, clan);
  const outsideFamily = !!record?.current_clan_tag && record.outside_family;
  const note = comparisonPublishNote(account, published);
  return (
    <article
      className={`player-card player-card-compact compare-account compare-account-${location.state}`}
    >
      <button
        type="button"
        className="player-card-body compare-player-body"
        aria-label={`Details for ${account.player_name}`}
        aria-describedby={`${id}-weight ${id}-meta ${id}-location${zone?.offsetMinutes != null ? ` ${id}-timezone` : ""}${outsideRange || outsideFamily ? ` ${id}-tags` : ""}${note ? ` ${id}-note` : ""}`}
        disabled={busy}
        onClick={onDetails}
      >
        <span className="player-card-top compare-player-top">
          <strong className="player-card-name" title={account.player_name}>
            <span className="player-card-inline-th" aria-hidden="true">
              <TownHallIcon level={account.town_hall} />
            </span>
            <span className="player-card-name-text">{account.player_name}</span>
          </strong>
          {account.effective_weight === null ? (
            <span id={`${id}-weight`} className="compare-tag is-danger">
              No weight
            </span>
          ) : (
            <strong
              id={`${id}-weight`}
              className="player-card-weight compare-player-weight"
            >
              {compactRosterWeight(account.effective_weight)}
            </strong>
          )}
        </span>
        <span className="compare-player-meta-line">
          <PlayerCardMeta
            account={account}
            id={`${id}-meta`}
            className="compare-player-meta"
          />
          {zone?.offsetMinutes != null && (
            <span
              id={`${id}-timezone`}
              className="compare-time-zone"
              aria-label={`Time zone ${zone.label}`}
            >
              {zone.label}
            </span>
          )}
        </span>
        <PlayerClanStatus
          id={`${id}-location`}
          className="compare-player-location"
          status={status}
        />
        {(outsideRange || outsideFamily) && (
          <span id={`${id}-tags`} className="compare-player-tags">
            {outsideRange && (
              <>
                <span className="sr-only">, </span>
                <span className="compare-tag is-warning">
                  Outside weight range
                </span>
              </>
            )}
            {outsideFamily && (
              <>
                <span className="sr-only">, </span>
                <span className="compare-tag is-warning">Outside family</span>
              </>
            )}
          </span>
        )}
        {note && (
          <span id={`${id}-note`} className="compare-publish-note" title={note}>
            {note}
          </span>
        )}
      </button>
      <RosterAccountMenu
        account={account}
        disabled={busy}
        onDetails={onDetails}
      />
    </article>
  );
}

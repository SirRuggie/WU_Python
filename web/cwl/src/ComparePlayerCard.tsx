import { useId } from "react";
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
  clan: RosterClan;
  record?: ComparisonLocation;
  now: number;
  published: PublishedComparisonAccount[] | null;
  busy: boolean;
  onDetails: () => void;
};
export default function ComparePlayerCard({
  account,
  clan,
  record,
  now,
  published,
  busy,
  onDetails,
}: Props) {
  const id = useId();
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
        aria-describedby={`${id}-weight ${id}-meta ${id}-location${outsideRange || outsideFamily ? ` ${id}-tags` : ""}${note ? ` ${id}-note` : ""}`}
        disabled={busy}
        onClick={onDetails}
      >
        <span className="player-card-top compare-player-top">
          <span aria-hidden="true">
            <TownHallIcon level={account.town_hall} />
          </span>
          <strong className="player-card-name" title={account.player_name}>
            {account.player_name}
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
        <PlayerCardMeta
          account={account}
          id={`${id}-meta`}
          className="compare-player-meta"
        />
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

import { useId } from "react";
import "./PlayerCard.css";
import TownHallIcon from "./TownHallIcon";
import { LockKeyhole } from "lucide-react";
import type { RosterAccount, RosterClan } from "./roster";
import RosterAccountMenu from "./RosterAccountMenu";
import {
  comparisonLocation,
  comparisonAge,
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
  const location = comparisonLocation(record, clan.tag, now);
  const note = comparisonPublishNote(account, published);
  return (
    <article
      className={`player-card compare-account compare-account-${location.state}`}
    >
      <button
        type="button"
        className="player-card-body compare-player-body"
        aria-label={`Details for ${account.player_name}`}
        aria-describedby={`${id}-weight ${id}-meta ${id}-location ${id}-tags${note ? ` ${id}-note` : ""}`}
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
        <span
          id={`${id}-meta`}
          className="player-card-meta compare-player-meta"
        >
          TH {account.town_hall ?? "—"} · {account.tag}
          {account.kept && (
            <LockKeyhole size={13} aria-label="Locked placement" />
          )}
        </span>
        <span id={`${id}-location`} className="compare-player-location">
          {location.state === "checking" ? (
            <span className="compare-location-label">Checking location…</span>
          ) : (
            <span className="compare-location-line" title={location.detail}>
              {record?.current_clan_name || record?.current_clan_tag ? (
                <>
                  <span className="compare-location-label">Now in </span>
                  <span className="compare-location-name">
                    {record.current_clan_name || record.current_clan_tag}
                  </span>
                </>
              ) : (
                <span className="compare-location-label">No clan</span>
              )}
              <span className="compare-location-age">
                <span className="sr-only">, </span>
                <span aria-hidden="true">· </span>
                {comparisonAge(record?.current_clan_checked_at, now)}
              </span>
            </span>
          )}
        </span>
        <span id={`${id}-tags`} className="compare-player-tags">
          <span
            className={`compare-tag compare-location-pill is-${location.state}`}
          >
            {location.label}
          </span>
          {outsideComparisonRange(account.effective_weight, clan) && (
            <>
              <span className="sr-only">, </span>
              <span className="compare-tag is-warning">
                Outside weight range
              </span>
            </>
          )}
          {record?.current_clan_tag && record.outside_family && (
            <>
              <span className="sr-only">, </span>
              <span className="compare-tag is-warning">Outside family</span>
            </>
          )}
        </span>
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

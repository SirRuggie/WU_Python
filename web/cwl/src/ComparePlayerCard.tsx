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
  const location = comparisonLocation(record, clan.tag, now);
  const note = comparisonPublishNote(account, published);
  return (
    <article className={`compare-account compare-account-${location.state}`}>
      <button
        type="button"
        className="compare-player-body"
        aria-label={`Details for ${account.player_name}`}
        disabled={busy}
        onClick={onDetails}
      >
        <span className="compare-player-top">
          <strong title={account.player_name}>{account.player_name}</strong>
          <strong>
            {account.effective_weight === null
              ? "—"
              : compactRosterWeight(account.effective_weight)}
          </strong>
        </span>
        <span className="compare-player-location">
          <span
            className={`compare-tag compare-location-pill is-${location.state}`}
          >
            {location.label}
          </span>
          {location.state !== "checking" && (
            <span className="compare-location-line" title={location.detail}>
              <span className="compare-location-name">
                {record?.current_clan_name || record?.current_clan_tag
                  ? `Now in: ${record.current_clan_name || record.current_clan_tag}`
                  : "No clan"}
              </span>
              <span className="compare-location-age">
                · {comparisonAge(record?.current_clan_checked_at, now)}
              </span>
            </span>
          )}
        </span>
        <span className="compare-player-tags">
          <span className="compare-player-meta">
            TH {account.town_hall ?? "—"} · {account.tag}{" "}
            {account.kept && (
              <LockKeyhole size={13} aria-label="Locked placement" />
            )}
          </span>
          {account.effective_weight === null && (
            <span className="compare-tag is-danger">No weight</span>
          )}
          {outsideComparisonRange(account.effective_weight, clan) && (
            <span className="compare-tag is-warning">Outside weight range</span>
          )}
          {record?.current_clan_tag && record.outside_family && (
            <span className="compare-tag is-warning">Outside family</span>
          )}
        </span>
        {note && (
          <span className="compare-publish-note" title={note}>
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

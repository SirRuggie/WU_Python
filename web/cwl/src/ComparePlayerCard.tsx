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
            {account.effective_weight === null ? (
              <span className="compare-tag is-danger">No weight</span>
            ) : (
              compactRosterWeight(account.effective_weight)
            )}
          </strong>
        </span>
        <span className="compare-player-context">
          <span className="compare-player-meta">
            {account.tag} · TH {account.town_hall ?? "—"}{" "}
            {account.kept && (
              <LockKeyhole size={15} aria-label="Locked placement" />
            )}
          </span>
          <span className="compare-location-line" title={location.detail}>
            {location.state !== "checking" && (
              <>
                <span className="compare-location-name">
                  {record?.current_clan_name || record?.current_clan_tag
                    ? `Now in: ${record.current_clan_name || record.current_clan_tag}`
                    : "No clan"}
                </span>
                <span className="compare-location-age">
                  · {comparisonAge(record?.current_clan_checked_at, now)}
                </span>
              </>
            )}
          </span>
        </span>
        <span className="compare-player-tags">
          <span className={`compare-tag is-${location.state}`}>
            {location.label}
          </span>
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

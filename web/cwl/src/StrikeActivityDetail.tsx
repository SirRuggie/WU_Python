import type { ActivityAccount } from "./strikeActivityView";
import { count } from "./strikeActivityFilters";
const date = (value?: string | null) =>
  value && Number.isFinite(Date.parse(value))
    ? new Date(value).toLocaleString()
    : "Unavailable";
export default function StrikeActivityDetail({
  account,
}: {
  account: Partial<ActivityAccount>;
}) {
  const wars = count(account.observed_wars),
    attacks = count(account.attacked_wars);
  const raids = count(account.observed_raid_weekends),
    attackedRaids = count(account.attacked_raid_weekends);
  const available = !account.activity_unavailable;
  return (
    <details className="strike-activity-detail">
      <summary>Activity details</summary>
      <dl>
        <dt>Last seen</dt>
        <dd>
          {available && account.last_seen_at
            ? `${date(account.last_seen_at)}${account.last_seen_source ? ` (${account.last_seen_source})` : ""}`
            : available && account.tracking_started_at
              ? `Not seen since tracking began (${date(account.tracking_started_at)})`
              : "Unavailable"}
        </dd>
        <dt>Quiet time</dt>
        <dd>
          {available &&
          !account.activity_tracking_behind &&
          account.last_seen_at &&
          count(account.quiet_days) !== null
            ? `Quiet for ${account.quiet_days} days`
            : "Unavailable"}
        </dd>
        <dt>Known wars</dt>
        <dd>
          {available &&
          wars !== null &&
          wars > 0 &&
          attacks !== null &&
          attacks <= wars
            ? `Attacked in ${attacks} of ${wars} known wars`
            : "Unavailable"}
        </dd>
        <dt>Consecutive wars without attacking</dt>
        <dd>
          {available &&
          wars !== null &&
          wars > 0 &&
          count(account.no_attack_wars) !== null &&
          account.no_attack_wars! <= wars
            ? `Didn't attack in their last ${account.no_attack_wars} known wars`
            : "Unavailable"}
        </dd>
        <dt>War attack slots</dt>
        <dd>
          {available &&
          count(account.observed_attacks) !== null &&
          account.observed_attacks! > 0 &&
          count(account.missed_attacks) !== null
            ? `Missed ${account.missed_attacks} of ${account.observed_attacks} observed war attacks`
            : "Unavailable"}
        </dd>
        <dt>Last attacking war ended</dt>
        <dd>
          {available ? date(account.last_attacked_war_end) : "Unavailable"}.
          This is the war end, not the exact attack time.
        </dd>
        <dt>Latest two ended raid weekends</dt>
        <dd>
          {available &&
          raids !== null &&
          raids > 0 &&
          attackedRaids !== null &&
          attackedRaids <= raids
            ? `Attacked in ${attackedRaids} of ${raids} known weekends${raids < 2 ? "; another weekend is unavailable" : ""}`
            : "Unavailable"}
        </dd>
        {account.replacement_note && (
          <>
            <dt>Staff note</dt>
            <dd>{account.replacement_note}</dd>
          </>
        )}
      </dl>
      <p>
        Unavailable or unusable history does not count as a missed attack.
        Current tracking delays may make activity incomplete.
      </p>
    </details>
  );
}

import { compactWeight } from "./replacementView";
import { memberName } from "./strikeActivityFilters";
import type { ActivityAccount } from "./strikeActivityView";
import { slotGroupKeys, slotVisibleCount } from "./slotSearchState";

export type SlotCandidate = Partial<ActivityAccount> & {
  player_tag: string;
  player_name: string;
  active_strikes: number;
  clan_tag?: string | null;
  clan_name?: string | null;
  weight_difference?: number | null;
  link_disputed?: boolean;
  departed?: boolean;
  left_label?: string | null;
  stale?: boolean;
  clan_seen_at?: string | null;
};
export type SlotGroup = {
  weight: number;
  weight_label: string;
  label?: string;
  source?: "typed" | "saved";
  account_tag?: string | null;
  link_disputed?: boolean;
  total: number;
  candidates: SlotCandidate[];
};
export type SlotResponse = {
  slots: SlotGroup[];
  unknown_weight?: number;
  weights_stale?: boolean;
  member_partial?: boolean;
  member_notice?: string | null;
  member_accounts?: {
    tag: string;
    name: string;
    saved_weight: number | null;
    link_disputed?: boolean;
  }[];
};
export function checkedSlotResponse(value: SlotResponse): SlotResponse {
  if (
    !Array.isArray(value.slots) ||
    value.slots.some(
      (group) =>
        !group ||
        !Number.isFinite(group.weight) ||
        group.weight <= 0 ||
        !Array.isArray(group.candidates) ||
        !Number.isInteger(group.total) ||
        group.total < group.candidates.length ||
        group.candidates.some(
          (row) =>
            !row ||
            typeof row.player_tag !== "string" ||
            typeof row.player_name !== "string" ||
            !Number.isInteger(row.active_strikes) ||
            row.active_strikes < 0,
        ),
    )
  )
    throw new Error("Slot results are incomplete. Try again.");
  return value;
}
/** A fresh slot remains actionable if it was absent from the earlier activity snapshot. */
function detailAccount(
  item: SlotCandidate,
  accounts: ActivityAccount[],
): ActivityAccount {
  const known = accounts.find((row) => row.player_tag === item.player_tag);
  return {
    total_strikes: item.active_strikes,
    marked_for_replacement: item.active_strikes >= 3,
    status: "risk",
    quiet_days: null,
    missed_attacks: 0,
    observed_attacks: 0,
    no_attack_wars: 0,
    skipped_raid_weekends: 0,
    activity_unavailable: true,
    ...known,
    ...item,
    current_clan_tag: item.departed
      ? null
      : (item.clan_tag ?? known?.current_clan_tag),
    current_clan_name: item.departed
      ? null
      : (item.clan_name ?? known?.current_clan_name),
    last_clan_tag: item.departed ? item.clan_tag : known?.last_clan_tag,
    last_clan_name: item.departed ? item.clan_name : known?.last_clan_name,
    left_clan: item.departed ?? known?.left_clan,
  };
}
export function lastSeenLabel(at?: string | null, now = Date.now()) {
  if (!at || !Number.isFinite(Date.parse(at))) return "Last seen unavailable";
  const hours = Math.max(0, Math.floor((now - Date.parse(at)) / 3600000));
  return `Last seen ${hours >= 24 ? `${Math.floor(hours / 24)} d` : `${hours} h`} ago`;
}
export default function SlotResults({
  data,
  accounts,
  expanded,
  disabled,
  onMore,
  onChoose,
}: {
  data: SlotResponse;
  accounts: ActivityAccount[];
  expanded: Record<string, number>;
  disabled: boolean;
  onMore: (key: string, count: number) => void;
  onChoose: (row: ActivityAccount) => void;
}) {
  const keys = slotGroupKeys(data.slots);
  return (
    <>
      {data.member_notice && (
        <p className="strike-slot-note">{data.member_notice}</p>
      )}
      {data.member_partial && (
        <p className="strike-slot-note">Some linked accounts were left out.</p>
      )}
      {data.weights_stale && (
        <p className="strike-slot-note">Some weights may be old</p>
      )}
      {data.member_accounts
        ?.filter((row) => !row.saved_weight)
        .map((row) => (
          <p key={row.tag} className="strike-slot-note">
            No saved weight:{" "}
            {row.name === row.tag ? row.tag : `${row.name} ${row.tag}`}
            {row.link_disputed ? " · Linked to two Discord users" : ""}
          </p>
        ))}
      {data.slots.map((group, index) => {
        const key = keys[index],
          shown = Math.min(
            group.candidates.length,
            slotVisibleCount(group, key, expanded),
          );
        const visible = group.candidates.slice(0, shown);
        return (
          <section
            className="strike-slot-group"
            key={key}
            aria-label={
              group.label || group.weight_label || compactWeight(group.weight)
            }
          >
            <header>
              <h3>
                {group.label ||
                  group.weight_label ||
                  compactWeight(group.weight)}
              </h3>
              <span>
                {shown} of {group.total}
              </span>
            </header>
            {group.link_disputed && (
              <p className="strike-slot-note">Linked to two Discord users</p>
            )}
            {visible.length ? (
              <ol>
                {visible.map((item) => {
                  const who = memberName(item);
                  return (
                    <li key={item.player_tag}>
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => onChoose(detailAccount(item, accounts))}
                      >
                        <span className="strike-slot-name">
                          <strong>{item.player_name}</strong>
                          {item.priority === "replace_first" ? (
                            <span className="strike-slot-priority strike-priority-chopping">
                              Chopping Block
                            </span>
                          ) : item.priority === "high" ? (
                            <span className="strike-slot-priority strike-priority-high">
                              High
                            </span>
                          ) : null}
                        </span>
                        <span className="strike-slot-gap">
                          <span>Gap</span>
                          <b>
                            {item.weight_difference != null
                              ? compactWeight(item.weight_difference)
                              : "—"}
                          </b>
                        </span>
                        <span className="strike-slot-context">
                          <span>
                            {item.town_hall ? `TH${item.town_hall}` : "TH—"}
                          </span>
                          <span>{item.clan_name || "Clan unavailable"}</span>
                          {who && <span>@{who}</span>}
                          <span>
                            {item.weight
                              ? compactWeight(item.weight)
                              : "Weight unavailable"}
                          </span>
                          <span>
                            {item.active_strikes}{" "}
                            {item.active_strikes === 1 ? "strike" : "strikes"}
                          </span>
                        </span>
                        {item.left_label && (
                          <span className="strike-slot-context">
                            {item.left_label}
                          </span>
                        )}
                        {item.stale && (
                          <span className="strike-slot-context">
                            {lastSeenLabel(
                              item.clan_seen_at ?? item.last_seen_at,
                            )}
                          </span>
                        )}
                        {item.link_disputed && (
                          <span className="strike-slot-context">
                            Linked to two Discord users
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ol>
            ) : (
              <div className="empty">
                <p>No slot in these clans</p>
              </div>
            )}
            {(data.unknown_weight ?? 0) > 0 && (
              <p>
                {data.unknown_weight}{" "}
                {data.unknown_weight === 1 ? "account has" : "accounts have"} no
                weight
              </p>
            )}
            {shown < group.total && shown < 100 && (
              <button
                className="strike-slot-more"
                type="button"
                disabled={disabled}
                onClick={() =>
                  onMore(
                    key,
                    Math.min(
                      100,
                      group.total,
                      slotVisibleCount(group, key, expanded) + 10,
                    ),
                  )
                }
              >
                Show more
                <span className="sr-only">
                  {" "}
                  for {group.label || group.weight_label}
                </span>
              </button>
            )}
          </section>
        );
      })}
    </>
  );
}

import { useRef } from "react";
import { ClipboardCheck } from "lucide-react";
import AccountCard from "./AccountCard";
import CardTally from "./CardTally";
import ActionMenu, { type ActionMenuItem } from "./rosterUi/ActionMenu";
import { StatusPill } from "./rosterUi/primitives";
import { discordMessageItem } from "./RosterAccountMenu";
import { infractionChips } from "./InfractionFields";
import {
  outcomeLabels,
  outcomeTone,
  participationOutcome,
} from "./participationOutcome";
import {
  attacksTally,
  bonusCandidateStatus,
  playerReasons,
  type BonusListMode,
  type RaffleAccount,
} from "./bonusRaffle";

type Props = {
  account: RaffleAccount;
  mode: BonusListMode;
  minimum: number | null;
  /** Opens the Infractions panel; absent on read-only lists. */
  onReview?: (account: RaffleAccount, opener: HTMLElement) => void;
  busy?: boolean;
};

/** One bonus candidate, in the same card as Results & participation. */
export default function BonusAccountCard({
  account,
  mode,
  minimum,
  onReview,
  busy = false,
}: Props) {
  const opener = useRef<HTMLButtonElement>(null);
  const outcome = participationOutcome(account, minimum);
  // Clan-wide reasons show once in the clan notice, not per card.
  const reasons = account.exclusion
    ? playerReasons(account)
    : [bonusCandidateStatus(account, mode)].filter(Boolean);
  const items: ActionMenuItem[] = [
    discordMessageItem(account.user_id),
    ...(onReview
      ? [
          {
            id: "review",
            label: "Infractions",
            icon: ClipboardCheck,
            disabled: busy,
            onAction: (trigger: HTMLElement) => onReview(account, trigger),
          },
        ]
      : []),
  ];
  return (
    <AccountCard
      className="bonus-account-card account-card-plain"
      thLevel={account.town_hall}
      name={
        onReview ? (
          <button
            ref={opener}
            type="button"
            className="account-card-open"
            aria-label={`Review ${account.player_name}`}
            disabled={busy}
            onClick={() => opener.current && onReview(account, opener.current)}
          >
            {account.player_name}
          </button>
        ) : (
          account.player_name
        )
      }
      meta={[
        <>TH {account.town_hall ?? "—"}</>,
        account.tag,
        account.manual_candidate ? "Added by staff" : null,
      ]}
      values={
        <CardTally
          attacks={attacksTally(account)}
          stars={account.stars ?? "—"}
          tone={outcome ? outcomeTone(outcome) : null}
        />
      }
      status={
        outcome
          ? {
              tone: "neutral",
              content: (
                <StatusPill
                  tone={outcomeTone(outcome)}
                  className="bonus-outcome"
                >
                  {outcomeLabels[outcome]}
                </StatusPill>
              ),
            }
          : undefined
      }
      flags={[
        reasons.length > 0 ? (
          <span className="bonus-account-reason">{reasons.join(" · ")}</span>
        ) : null,
        account.attacks_override ? "Staff correction" : null,
        account.multiplier === 2 ? "2× ticket weight" : null,
        ...infractionChips(account.bonus_review),
      ]}
      action={<ActionMenu name={account.player_name} items={items} />}
    />
  );
}

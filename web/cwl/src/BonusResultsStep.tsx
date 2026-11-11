import type { ReactNode } from "react";
import BonusAccountList from "./BonusAccountList";
import BonusBlockers from "./BonusBlockers";
import type { BonusBlockerLine, RaffleAccount } from "./bonusRaffle";

type Props = {
  lines: BonusBlockerLine[];
  fix: (line: BonusBlockerLine) => ReactNode;
  accounts: RaffleAccount[];
  minimum: number | null;
  onReview?: (account: RaffleAccount, opener: HTMLElement) => void;
  busy: boolean;
};

/** Step 1: the clan's players with their results. Not checked players are fixed here. */
export default function BonusResultsStep({
  lines,
  fix,
  accounts,
  minimum,
  onReview,
  busy,
}: Props) {
  return (
    <>
      <BonusBlockers lines={lines} fix={fix} />
      <BonusAccountList
        accounts={accounts}
        minimum={minimum}
        onReview={onReview}
        busy={busy}
        searchable
      />
    </>
  );
}

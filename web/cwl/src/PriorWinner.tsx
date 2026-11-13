import { Chip } from "./rosterUi/primitives";

type PriorWin = {
  pool: string;
  sit_out_excluded?: boolean;
  /** FWA Rep account on the list: its prior win does not block it. */
  sit_out_exempt?: boolean;
  prior_winner_cycle?: string | null;
  eligible_again?: string | null;
};

export const winnerMonth = (cycle: string | null | undefined, long = false) => {
  if (!cycle || !/^\d{4}-(0[1-9]|1[0-2])$/.test(cycle)) return "";
  return new Intl.DateTimeFormat("en-US", {
    month: long ? "long" : "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${cycle}-01T00:00:00Z`));
};

/** Only Results/bonus surfaces import this; a staff exception removes the pill. */
export default function PriorWinner({
  account,
  details = false,
}: {
  account: PriorWin;
  details?: boolean;
}) {
  const month = winnerMonth(account.prior_winner_cycle);
  if (account.pool === "lazy" && account.sit_out_exempt && month)
    return <Chip>FWA Rep · no sit-out</Chip>;
  if (account.pool !== "lazy" || !account.sit_out_excluded || !month)
    return null;
  return (
    <>
      <Chip>Prior winner · {month}</Chip>
      {details && account.eligible_again && (
        <p>Eligible again: {winnerMonth(account.eligible_again, true)}</p>
      )}
    </>
  );
}

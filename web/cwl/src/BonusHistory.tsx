import BonusAccountList from "./BonusAccountList";
import { exportMonthLabel } from "./exportPreview";
import { resultDateText } from "./participationOutcome";
import type { RaffleData } from "./bonusRaffle";

/** Saved bonus history: cancelled draws and approved awards. */
export default function BonusHistory({ data }: { data: RaffleData }) {
  return (
    <details className="bonus-history">
      <summary>Saved bonus history ({data.history.length})</summary>
      <p className="small">
        Dashboard selections only; this is not proof medals were awarded
        in-game.
      </p>
      {data.draws
        .filter((item) => item.cancelled_at)
        .map((item) => (
          <div className="bonus-history-row" key={`cancelled-${item.id}`}>
            <strong>{item.snapshot.clan_name} · Cancelled draw</strong>
            <p>{item.cancel_reason}</p>
            <small>{resultDateText(item.cancelled_at!)}</small>
            <BonusAccountList accounts={item.snapshot.winners} mode="winners" />
          </div>
        ))}
      {data.history.map((item) => (
        <div className="bonus-history-row" key={item.id}>
          <strong>
            {item.player_name} · {item.clan_name || item.clan_tag}
          </strong>
          <small>
            {item.tag} · {exportMonthLabel(item.cycle)} ·{" "}
            {item.voided_at ? "Voided" : "Approved"} ·{" "}
            {resultDateText(item.confirmed_at)}
          </small>
        </div>
      ))}
    </details>
  );
}

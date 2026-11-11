import { useEffect, useState } from "react";
import BonusAccountList from "./BonusAccountList";
import { api, ApiError } from "./api";
import { exportMonthLabel } from "./exportPreview";
import { resultDateText } from "./participationOutcome";
import type { RaffleData } from "./bonusRaffle";
import "./ResultsHistory.css";

/** Saved bonus history: cancelled draws and approved awards. Read only; fetched only while open. */
export default function BonusHistory({
  seasonId,
  onAccessDenied,
}: {
  seasonId: string;
  onAccessDenied?: (error: ApiError) => void;
}) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<RaffleData | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setData(null);
    setError("");
    api<RaffleData>(`/seasons/${encodeURIComponent(seasonId)}/bonus-raffle`)
      .then((result) => {
        if (active) setData(result);
      })
      .catch((cause) => {
        if (!active) return;
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          onAccessDenied?.(cause);
        setError(
          cause instanceof Error ? cause.message : "Could not load history.",
        );
      });
    return () => {
      active = false;
    };
  }, [open, seasonId, attempt]);

  return (
    <details
      className="bonus-history"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>
        Saved bonus history{data ? ` (${data.history.length})` : ""} · read only
      </summary>
      {open && (
        <>
          <p className="small">
            Dashboard selections only; this is not proof medals were awarded
            in-game.
          </p>
          {error && (
            <p role="alert">
              {error}{" "}
              <button type="button" onClick={() => setAttempt((v) => v + 1)}>
                Retry history
              </button>
            </p>
          )}
          {!data && !error && <p role="status">Loading history…</p>}
          {data &&
            !data.history.length &&
            !data.draws.some((item) => item.cancelled_at) && (
              <p>No saved bonus history yet.</p>
            )}
          {data?.draws
            .filter((item) => item.cancelled_at)
            .map((item) => (
              <div className="bonus-history-row" key={`cancelled-${item.id}`}>
                <strong>{item.snapshot.clan_name} · Cancelled draw</strong>
                <p>{item.cancel_reason}</p>
                <small>{resultDateText(item.cancelled_at!)}</small>
                <BonusAccountList
                  accounts={item.snapshot.winners}
                  mode="winners"
                />
              </div>
            ))}
          {data?.history.map((item) => (
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
        </>
      )}
    </details>
  );
}

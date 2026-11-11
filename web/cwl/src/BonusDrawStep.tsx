import type { ReactNode } from "react";
import BonusAccountList from "./BonusAccountList";
import type { Pool } from "./api";
import type { RafflePreview, SavedDraw } from "./bonusRaffle";

type Props = {
  pool: Pool;
  /** "Finish Results first." and similar; hides the action. */
  gate: string;
  /** First blocker of this step, shown under the action. */
  blocker: string;
  draw: SavedDraw | undefined;
  preview: RafflePreview | null;
  busy: boolean;
  minimum: number | null;
  canSave: boolean;
  /** Extra fix beside one blocking reason of the preview. */
  reasonFix: (reason: string) => ReactNode;
  onDraw: () => void;
};

/** Step 3: the preview loads on its own; one button saves the winners. */
export default function BonusDrawStep({
  pool,
  gate,
  blocker,
  draw,
  preview,
  busy,
  minimum,
  canSave,
  reasonFix,
  onDraw,
}: Props) {
  if (draw)
    return (
      <>
        <div className="bonus-stats">
          <div>
            <strong>{draw.snapshot.winners.length}</strong>
            <span>Winners</span>
          </div>
          <div>
            <strong>{draw.snapshot.eligible.length}</strong>
            <span>Eligible</span>
          </div>
          <div>
            <strong>{draw.snapshot.slots}</strong>
            <span>Bonus allowance</span>
          </div>
        </div>
        <details className="bonus-secondary">
          <summary>Draw details and all eligible accounts</summary>
          <p>
            {draw.snapshot.allowance_source === "automatic"
              ? "Calculated"
              : "Staff-confirmed"}{" "}
            allowance · Saved results do not change if the rules change later.
          </p>
          <BonusAccountList
            accounts={draw.snapshot.eligible}
            mode="eligible"
            minimum={draw.snapshot.minimum}
          />
        </details>
      </>
    );
  if (gate) return <p className="bonus-action-blocker">{gate}</p>;
  if (!preview)
    return blocker ? (
      <p className="bonus-action-blocker">{blocker}</p>
    ) : (
      <p className="bonus-empty" role="status">
        {busy ? "Working…" : "The draw preview is not loaded."}
      </p>
    );
  const all = preview.available >= preview.eligible.length;
  return (
    <section className="bonus-preview" aria-label="Draw preview">
      <div className="bonus-section-heading">
        <h3>
          {preview.eligible.length} eligible ·{" "}
          {Math.min(preview.available, preview.eligible.length)} winners
        </h3>
        <span>{preview.available} slots remaining</span>
      </div>
      <p>
        {preview.allowance_source === "automatic"
          ? "Calculated"
          : "Staff-confirmed"}{" "}
        allowance · {preview.slots} total bonuses
        {pool === "main" && preview.minimum !== null
          ? ` · Minimum ${preview.minimum} attacks`
          : ""}
      </p>
      {all && <p>Every eligible account will win. Unused slots remain open.</p>}
      {!!preview.blocking_reasons.length && (
        <div className="notice error" role="alert">
          {preview.blocking_reasons.map((reason) => (
            <p key={reason}>
              {reason}
              {reasonFix(reason)}
            </p>
          ))}
          <p>Check Clash now before you draw.</p>
        </div>
      )}
      <h4>In the draw</h4>
      <BonusAccountList
        accounts={preview.eligible}
        mode="eligible"
        minimum={minimum}
      />
      <details className="bonus-secondary">
        <summary>Excluded ({preview.excluded.length})</summary>
        <BonusAccountList
          accounts={preview.excluded}
          mode="excluded"
          minimum={minimum}
        />
      </details>
      <div className="bonus-action-bar">
        <span>Saved draws cannot be redrawn by refreshing.</span>
        <button
          type="button"
          className="primary"
          disabled={!canSave}
          onClick={onDraw}
        >
          {all ? "Save all winners" : "Draw and save winners"}
        </button>
      </div>
      {blocker && <p className="bonus-action-blocker">{blocker}</p>}
    </section>
  );
}

import BonusAccountList from "./BonusAccountList";
import type { SavedDraw } from "./bonusRaffle";
import { resultDateText } from "./participationOutcome";

type Props = {
  gate: string;
  blocker: string;
  draw: SavedDraw | undefined;
  disabled: boolean;
  cancelDisabled: boolean;
  cancelReason: string;
  onCancelReason: (value: string) => void;
  onApprove: () => void;
  onCancel: () => void;
};

/** Step 4: the saved winners, Approve winners, and Cancel this draw. */
export default function BonusApproveStep({
  gate,
  blocker,
  draw,
  disabled,
  cancelDisabled,
  cancelReason,
  onCancelReason,
  onApprove,
  onCancel,
}: Props) {
  if (!draw) return <p className="bonus-action-blocker">{gate}</p>;
  return (
    <>
      <p className="bonus-step-note">
        Saved {resultDateText(draw.created_at)} ·{" "}
        {draw.approved_at ? "Approved" : "Awaiting staff approval"}
      </p>
      <BonusAccountList
        accounts={draw.snapshot.winners}
        mode="winners"
        minimum={draw.snapshot.minimum}
      />
      {!draw.approved_at && (
        <>
          <div className="bonus-action-bar">
            <span>
              Approval records the winners. It does not send a message.
            </span>
            <button
              type="button"
              className="primary"
              disabled={disabled}
              onClick={onApprove}
            >
              Approve winners
            </button>
          </div>
          {blocker && <p className="bonus-action-blocker">{blocker}</p>}
          <details className="bonus-secondary">
            <summary>Cancel this draw</summary>
            <p>
              Cancel only if the results or setup are wrong. The winners and the
              reason stay in history.
            </p>
            <label>
              Reason
              <textarea
                name="cancel-reason"
                autoComplete="off"
                maxLength={500}
                value={cancelReason}
                disabled={disabled}
                onChange={(event) => onCancelReason(event.target.value)}
              />
            </label>
            <button type="button" disabled={cancelDisabled} onClick={onCancel}>
              Confirm cancellation
            </button>
          </details>
        </>
      )}
    </>
  );
}

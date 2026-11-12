import PriorWinner from "./PriorWinner";
import ActionPanel from "./ActionPanel";
import DiscordIdentity from "./DiscordIdentity";
import { useEffect } from "react";
import type { RaffleAccount } from "./bonusRaffle";
import InfractionFields, { useInfractionDraft } from "./InfractionFields";

type Props = {
  account: RaffleAccount;
  /** The card control that opened the panel; focus returns to it. */
  trigger: HTMLElement | null;
  busy: boolean;
  error: string;
  onCancel: () => void;
  onDirty: (dirty: boolean) => void;
  onSave: (flags: string[], overrideReason: string) => Promise<boolean>;
  onRemove?: () => Promise<void>;
  /** After the clan's draw is saved the flags can be read but not changed. */
  readOnly?: boolean;
};

export default function BonusCandidateReview({
  account,
  trigger,
  busy,
  error,
  onCancel,
  onDirty,
  onSave,
  onRemove,
  readOnly = false,
}: Props) {
  const { flags, setFlags, reason, setReason, dirty } = useInfractionDraft(
    account.bonus_review,
  );

  useEffect(() => onDirty(dirty), [dirty, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);

  return (
    <ActionPanel
      title={`Infractions for ${account.player_name}`}
      className="bonus-review-editor"
      trigger={trigger}
      busy={busy}
      onClose={() => {
        // Close, Escape, backdrop and Back all go through the discard guard.
        onCancel();
        // false keeps the Back entry while the discard question is open.
        return dirty ? false : undefined;
      }}
      footer={
        <div className="bonus-editor-actions">
          {onRemove && !readOnly && (
            <button
              type="button"
              className="bonus-remove-candidate"
              disabled={busy}
              onClick={() => void onRemove()}
            >
              Remove candidate
            </button>
          )}
          <button type="button" disabled={busy} onClick={onCancel}>
            {readOnly ? "Close" : "Cancel"}
          </button>
          {!readOnly && (
            <button
              type="button"
              className="primary"
              disabled={busy || !dirty || (!!reason && !reason.trim())}
              onClick={() => void onSave(flags, reason.trim())}
            >
              Save infractions
            </button>
          )}
        </div>
      }
    >
      <p className="bonus-review-tag">{account.tag}</p>
      <div className="bonus-review-context">
        {account.exclusion && (
          <p>
            <strong>Current exclusion:</strong> {account.exclusion}
          </p>
        )}
        <PriorWinner account={account} details />
        {account.manual_candidate_reason && (
          <p>
            <strong>Added by staff:</strong> {account.manual_candidate_reason}
          </p>
        )}
        {account.bonus_review?.updated_at && (
          <p className="bonus-review-attribution">
            Last review saved{" "}
            {new Date(account.bonus_review.updated_at).toLocaleString()}
            {account.bonus_review.updated_by && (
              <>
                {" "}
                by{" "}
                <DiscordIdentity
                  userId={account.bonus_review.updated_by}
                  variant="compact"
                />
              </>
            )}
            .
          </p>
        )}
      </div>
      <p>
        Mark issues from this CWL month. These flags normally exclude the
        account from the draw.
      </p>
      {readOnly && (
        <p className="bonus-review-readonly">Draw saved · read only</p>
      )}
      <InfractionFields
        flags={flags}
        reason={reason}
        disabled={busy || readOnly}
        onFlags={setFlags}
        onReason={setReason}
      />
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
    </ActionPanel>
  );
}

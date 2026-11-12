import { useState, type ReactNode } from "react";
import type { BonusReview } from "./bonusRaffle";
import { Chip } from "./rosterUi/primitives";
import "./BonusWorkspace.css";

export const LAZY_FLAGS = [
  {
    id: "missed_sync",
    label: "Missed sync",
    description: "Account missed the clan sync during CWL.",
  },
  {
    id: "lingering",
    label: "Lingering",
    description: "Account stayed after it should have moved.",
  },
  {
    id: "left_family",
    label: "Left family",
    description: "Account left the family during this CWL month.",
  },
] as const;

export const flagLabel = (flag: string) =>
  LAZY_FLAGS.find((item) => item.id === flag)?.label || flag;

/** Card chips: one per set flag, then "Staff reason" when an override is saved. */
export const infractionChips = (
  review: BonusReview | null | undefined,
): ReactNode[] => [
  ...(review?.flags || []).map((flag) => (
    <Chip key={flag}>{flagLabel(flag)}</Chip>
  )),
  ...(review?.override_reason ? [<Chip key="reason">Staff reason</Chip>] : []),
];

/** The editable flags and staff reason, against the saved review. */
export function useInfractionDraft(review: BonusReview | null | undefined) {
  const savedFlags = review?.flags || [];
  const savedReason = review?.override_reason || "";
  const [flags, setFlags] = useState<string[]>(savedFlags);
  const [reason, setReason] = useState(savedReason);
  const dirty =
    flags.slice().sort().join("|") !== savedFlags.slice().sort().join("|") ||
    reason !== savedReason;
  return { flags, setFlags, reason, setReason, dirty };
}

type Props = {
  flags: string[];
  reason: string;
  disabled: boolean;
  onFlags: (flags: string[]) => void;
  onReason: (reason: string) => void;
};

/** Flag checkboxes and the staff exception, shared by every Infractions editor. */
export default function InfractionFields({
  flags,
  reason,
  disabled,
  onFlags,
  onReason,
}: Props) {
  return (
    <>
      <fieldset disabled={disabled}>
        <legend>Season flags</legend>
        {LAZY_FLAGS.map((flag) => (
          <label key={flag.id} className="bonus-flag">
            <input
              type="checkbox"
              checked={flags.includes(flag.id)}
              onChange={(event) =>
                onFlags(
                  event.target.checked
                    ? [...flags, flag.id]
                    : flags.filter((value) => value !== flag.id),
                )
              }
            />
            <span>
              <strong>{flag.label}</strong>
              <small>{flag.description}</small>
            </span>
          </label>
        ))}
      </fieldset>
      <label className="bonus-override-reason">
        Include by staff exception
        <textarea
          value={reason}
          maxLength={500}
          disabled={disabled}
          onChange={(event) => onReason(event.target.value)}
          placeholder="Leave blank to follow the automatic rules; enter a reason to override exclusion"
        />
      </label>
      {reason.trim() && (
        <p className="bonus-caution">
          This account can enter the draw despite an automatic rule or flag. The
          reason is saved with the review.
        </p>
      )}
    </>
  );
}

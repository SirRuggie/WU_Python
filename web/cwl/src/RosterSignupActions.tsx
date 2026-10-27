import { useEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { ArrowRightLeft, Trash2 } from "lucide-react";
import { Button, Chip, StatusPill } from "./rosterUi/primitives";
import type { Pool } from "./api";
import type { RosterAccount, RosterClan } from "./roster";
import "./RosterSignupActions.css";

export type SignupAction = Pool | "remove";

type Props = {
  accounts: RosterAccount[];
  clans: RosterClan[];
  busy: boolean;
  error?: string;
  onApply: (action: SignupAction, tags: string[]) => Promise<boolean>;
  onReviewChange: (reviewing: boolean) => void;
  hiddenTags?: string[];
  footerTarget?: HTMLElement | null;
};

type ReviewProps = {
  accounts: RosterAccount[];
  clans: RosterClan[];
  action: SignupAction;
  hiddenTags?: string[];
  busy: boolean;
  error?: string;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  onCancel: () => void;
  onConfirm: () => void;
  footerTarget?: HTMLElement | null;
};

const actionLabel: Record<SignupAction, string> = {
  main: "Switch to Main CWL",
  lazy: "Switch to Lazy CWL",
  remove: "Remove signups",
};

export function RosterSignupReview({
  accounts,
  clans,
  action,
  busy,
  error,
  headingRef,
  onCancel,
  onConfirm,
  hiddenTags = [],
  footerTarget,
}: ReviewProps) {
  const changed = accounts.filter(
    (account) => action === "remove" || account.pool !== action,
  );
  const assigned = changed.filter(
    (account) => !!account.assigned_clan_tag,
  ).length;
  const hostName = (tag: string | null) =>
    clans.find((clan) => clan.tag === tag)?.name || tag || "Unassigned";
  const reviewActions = (
    <div className="roster-signup-review-actions">
      <Button disabled={busy} onClick={onCancel}>
        Cancel
      </Button>
      <Button
        variant={action === "remove" ? "danger" : "primary"}
        disabled={busy}
        onClick={onConfirm}
      >
        {busy ? "Saving…" : `Confirm ${actionLabel[action].toLowerCase()}`}
      </Button>
    </div>
  );

  return (
    <div
      className="roster-signup-review"
      role="group"
      aria-labelledby="signup-review-title"
      onKeyDown={(event) => {
        if (event.key !== "Escape" || busy) return;
        event.preventDefault();
        event.stopPropagation();
        onCancel();
      }}
    >
      <h3 id="signup-review-title" tabIndex={-1} ref={headingRef}>
        Review {actionLabel[action]}
      </h3>
      <p>
        {changed.length} of {accounts.length} selected account
        {accounts.length === 1 ? "" : "s"} will change.
        {assigned > 0 &&
          ` ${assigned} working placement${assigned === 1 ? "" : "s"} will be cleared.`}{" "}
        {action !== "remove"
          ? "The working placement and lock are cleared. Signup type changes are visible to members immediately."
          : "Signup removal is visible to members immediately."}{" "}
        Published rosters stay unchanged until republished.
      </p>
      <ul>
        {accounts.map((account) => (
          <li key={account.tag}>
            <strong>{account.player_name}</strong>
            <small>
              {account.tag} · {account.pool === "main" ? "Main" : "Lazy"} CWL
              {account.kept && (action === "remove" || account.pool !== action)
                ? " · Locked — affected"
                : ""}
              {hiddenTags.includes(account.tag) ? " · Not visible in list" : ""}
              {account.assigned_clan_tag
                ? ` · Assigned to ${hostName(account.assigned_clan_tag)}`
                : " · unassigned"}
            </small>
          </li>
        ))}
      </ul>
      {error && (
        <p role="alert" className="roster-signup-error">
          <StatusPill tone="danger">{error}</StatusPill>
        </p>
      )}
      {footerTarget ? createPortal(reviewActions, footerTarget) : reviewActions}
    </div>
  );
}

export default function RosterSignupActions({
  accounts,
  clans,
  busy,
  error,
  onApply,
  onReviewChange,
  hiddenTags = [],
  footerTarget,
}: Props) {
  const [action, setAction] = useState<SignupAction | "">("");
  const [reviewing, setReviewing] = useState(false);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const reviewButton = useRef<HTMLButtonElement | null>(null);
  const pendingApply = useRef(false);
  const tags = accounts.map((account) => account.tag);
  const changed = accounts.filter(
    (account) => action === "remove" || account.pool !== action,
  );

  useEffect(() => {
    onReviewChange(reviewing);
    return () => onReviewChange(false);
  }, [reviewing, onReviewChange]);
  useEffect(() => {
    if (reviewing) reviewHeading.current?.focus();
  }, [reviewing]);

  function cancelReview() {
    setReviewing(false);
    requestAnimationFrame(() =>
      reviewButton.current?.focus({ preventScroll: true }),
    );
  }

  async function apply() {
    if (!action || busy || pendingApply.current || !changed.length) return;
    pendingApply.current = true;
    try {
      const saved = await onApply(action, tags);
      if (saved) setReviewing(false);
    } finally {
      pendingApply.current = false;
    }
  }

  return (
    <section
      className="roster-ui roster-signup-actions"
      aria-label="Selected signup actions"
    >
      {!reviewing ? (
        <>
          {(["main", "lazy", "remove"] as const).map((choice) => {
            const affected = accounts.filter(
              (account) => choice === "remove" || account.pool !== choice,
            ).length;
            return (
              <div className="roster-signup-option" key={choice}>
                <Button
                  variant={choice === "remove" ? "danger" : "secondary"}
                  icon={choice === "remove" ? Trash2 : ArrowRightLeft}
                  disabled={busy || !affected || accounts.length > 50}
                  onClick={(event) => {
                    reviewButton.current = event.currentTarget;
                    setAction(choice);
                    setReviewing(true);
                  }}
                >
                  {actionLabel[choice]} · {affected}
                </Button>
                {!affected && (
                  <small>
                    All selected accounts are already in{" "}
                    {choice === "main" ? "Main CWL" : "Lazy CWL"}.
                  </small>
                )}
              </div>
            );
          })}
          {!!hiddenTags.length && (
            <details>
              <summary>
                <Chip tone="info">
                  {hiddenTags.length} selected accounts not visible in the list
                </Chip>
              </summary>
              <ul>
                {accounts
                  .filter((a) => hiddenTags.includes(a.tag))
                  .map((a) => (
                    <li key={a.tag}>
                      {a.player_name} · {a.tag}
                    </li>
                  ))}
              </ul>
            </details>
          )}
        </>
      ) : action ? (
        <RosterSignupReview
          accounts={accounts}
          hiddenTags={hiddenTags}
          clans={clans}
          action={action}
          busy={busy}
          error={error}
          headingRef={reviewHeading}
          footerTarget={footerTarget}
          onCancel={cancelReview}
          onConfirm={() => void apply()}
        />
      ) : null}
    </section>
  );
}

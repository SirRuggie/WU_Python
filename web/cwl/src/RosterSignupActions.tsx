import { useEffect, useRef, useState, type RefObject } from "react";
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
};

type ReviewProps = {
  accounts: RosterAccount[];
  clans: RosterClan[];
  action: SignupAction;
  busy: boolean;
  error?: string;
  headingRef?: RefObject<HTMLHeadingElement | null>;
  onCancel: () => void;
  onConfirm: () => void;
};

const actionLabel: Record<SignupAction, string> = {
  main: "Switch to Main CWL",
  lazy: "Switch to Lazy CWL",
  remove: "Remove signups",
};

export function RosterSignupReview({ accounts, clans, action, busy, error, headingRef, onCancel, onConfirm }: ReviewProps) {
  const changed = accounts.filter((account) => action === "remove" || account.pool !== action);
  const assigned = changed.filter((account) => !!account.assigned_clan_tag).length;
  const hostName = (tag: string | null) => clans.find((clan) => clan.tag === tag)?.name || tag || "Unassigned";

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
      <h3 id="signup-review-title" tabIndex={-1} ref={headingRef}>Review {actionLabel[action]}</h3>
      <p>
        {changed.length} of {accounts.length} selected account{accounts.length === 1 ? "" : "s"} will change.
        {assigned > 0 && ` ${assigned} working placement${assigned === 1 ? "" : "s"} will be cleared.`}
        {" "}Published rosters stay unchanged until republished.
      </p>
      <ul>
        {accounts.map((account) => (
          <li key={account.tag}>
            <strong>{account.player_name}</strong>
            <small>
              {account.tag} · {account.pool === "main" ? "Main" : "Lazy"} CWL
              {account.assigned_clan_tag ? ` · Assigned to ${hostName(account.assigned_clan_tag)}` : " · unassigned"}
            </small>
          </li>
        ))}
      </ul>
      {error && <p role="alert">{error}</p>}
      <div className="roster-signup-review-actions">
        <button type="button" disabled={busy} onClick={onCancel}>Cancel</button>
        <button type="button" className={action === "remove" ? "danger" : "primary"} disabled={busy} onClick={onConfirm}>
          {busy ? "Saving…" : `Confirm ${actionLabel[action].toLowerCase()}`}
        </button>
      </div>
    </div>
  );
}

export default function RosterSignupActions({ accounts, clans, busy, error, onApply, onReviewChange }: Props) {
  const [action, setAction] = useState<SignupAction | "">("");
  const [reviewing, setReviewing] = useState(false);
  const reviewHeading = useRef<HTMLHeadingElement>(null);
  const reviewButton = useRef<HTMLButtonElement>(null);
  const pendingApply = useRef(false);
  const tags = accounts.map((account) => account.tag);
  const changed = accounts.filter((account) => action === "remove" || account.pool !== action);

  useEffect(() => {
    onReviewChange(reviewing);
    return () => onReviewChange(false);
  }, [reviewing, onReviewChange]);
  useEffect(() => {
    if (reviewing) reviewHeading.current?.focus();
  }, [reviewing]);

  function cancelReview() {
    setReviewing(false);
    requestAnimationFrame(() => reviewButton.current?.focus({ preventScroll: true }));
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
    <section className="roster-signup-actions" aria-label="Selected signup actions">
      {!reviewing ? (
        <>
          <label>
            Signup change
            <select value={action} disabled={busy} onChange={(event) => setAction(event.target.value as SignupAction | "")}>
              <option value="">Choose an action</option>
              <option value="main">Switch to Main CWL</option>
              <option value="lazy">Switch to Lazy CWL</option>
              <option value="remove">Remove signups</option>
            </select>
          </label>
          <button type="button" ref={reviewButton} disabled={busy || !action || !changed.length} onClick={() => setReviewing(true)}>
            Review signup change
          </button>
          {action && !changed.length && <small>All selected accounts already have this signup type.</small>}
        </>
      ) : action ? (
        <RosterSignupReview
          accounts={accounts}
          clans={clans}
          action={action}
          busy={busy}
          error={error}
          headingRef={reviewHeading}
          onCancel={cancelReview}
          onConfirm={() => void apply()}
        />
      ) : null}
    </section>
  );
}

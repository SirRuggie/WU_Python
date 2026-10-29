import { useEffect, useRef, useState } from "react";
import { ChevronRight, TriangleAlert } from "lucide-react";
import ActionPanel from "./ActionPanel";
import ConfirmDialog from "./ConfirmDialog";
import DiscordContact from "./DiscordContact";
import { Button } from "./rosterUi/primitives";
import type { RosterSnapshot } from "./roster";
import { publicationDate } from "./publicationStatus";
import {
  signupActivityIntro,
  signupChangeLabel,
  signupShortage,
  signupPoolName,
  type SignupChange,
} from "./signupActivityModel";
import useSignupActivity from "./useSignupActivity";
import "./SignupActivity.css";

type Props = {
  seasonId: string;
  roster: RosterSnapshot | null;
  publishedVersion?: number;
  disabled?: boolean;
  canCompare: boolean;
  onFill: (item: SignupChange) => boolean;
  onDetails: (tag: string) => boolean;
};
export default function SignupActivity({
  seasonId,
  roster,
  publishedVersion,
  disabled,
  canCompare,
  onFill,
  onDetails,
}: Props) {
  const activity = useSignupActivity(seasonId);
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState<SignupChange[] | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const shortage = signupShortage(activity.items, roster?.clans ?? []);
  useEffect(() => {
    if (!activity.items.length && activity.busy === null) {
      setOpen(false);
      setConfirm(null);
    }
  }, [activity.items.length, activity.busy]);
  const busy = activity.busy !== null;
  return (
    <div className="signup-activity" aria-live="polite">
      {activity.error ? (
        <div className="signup-activity-load-error">
          Couldn't check signup changes ·{" "}
          <Button onClick={activity.retry}>Retry</Button>
        </div>
      ) : (
        activity.items.length > 0 && (
          <>
            <button
              ref={trigger}
              className="signup-activity-line"
              disabled={disabled}
              onClick={() => setOpen(true)}
            >
              <span aria-hidden="true">🔁</span>
              <span>{signupChangeLabel(activity.items)}</span>
            </button>
            {shortage && (
              <button
                className="signup-activity-line is-danger"
                disabled={disabled || !canCompare}
                onClick={() => onFill(shortage.item)}
              >
                <TriangleAlert size={16} aria-hidden="true" />
                <span>{shortage.text}</span>
                <ChevronRight size={16} aria-hidden="true" />
              </button>
            )}
          </>
        )
      )}
      {open && (
        <ActionPanel
          title="Signup changes"
          variant="side"
          className={`roster-ui signup-activity-panel${shortage ? " is-danger" : ""}`}
          trigger={trigger.current}
          busy={busy || !!confirm}
          onClose={() => setOpen(false)}
        >
          <p className="signup-activity-intro">
            {signupActivityIntro(publishedVersion)}
          </p>
          {activity.result && <p role="status">{activity.result}</p>}
          {activity.items.map((item) => (
            <article className="signup-activity-row" key={item.id}>
              <div className="signup-activity-identity">
                <strong>
                  {item.action === "member_pool_change" &&
                  roster?.accounts.some(
                    (account) => account.tag === item.tag,
                  ) ? (
                    <button
                      className="signup-activity-name"
                      disabled={busy}
                      onClick={() => {
                        if (onDetails(item.tag)) setOpen(false);
                      }}
                    >
                      {item.player_name}
                    </button>
                  ) : (
                    item.player_name
                  )}
                  {item.action === "member_withdrawal"
                    ? " withdrew"
                    : ` switched to ${signupPoolName(item.to_pool)}`}
                </strong>
                <time
                  dateTime={item.created_at}
                  title={new Date(item.created_at).toLocaleString()}
                >
                  {publicationDate(item.created_at)}
                </time>
              </div>
              <p>
                {item.tag} · was in {item.assigned_clan_name || "previous clan"}{" "}
                ({signupPoolName(item.from_pool)})
              </p>
              <div className="signup-activity-actions">
                <Button
                  disabled={busy || !canCompare}
                  title={
                    !canCompare ? "Build roster access required" : undefined
                  }
                  onClick={() => {
                    if (onFill(item)) setOpen(false);
                  }}
                >
                  Fill spot ›
                </Button>
                <DiscordContact
                  userId={item.user_id}
                  label="Message ↗"
                  className="roster-ui roster-ui-button is-secondary"
                />
                <Button
                  className="signup-activity-review"
                  disabled={busy}
                  onClick={() => void activity.review([item])}
                >
                  {activity.busy === item.id ? "Saving…" : "Mark reviewed"}
                </Button>
              </div>
              {activity.rowErrors[item.id] && (
                <p className="signup-activity-row-error" role="alert">
                  {activity.rowErrors[item.id]}
                </p>
              )}
            </article>
          ))}
          {activity.items.length >= 2 && (
            <Button
              disabled={busy}
              onClick={() => setConfirm([...activity.items])}
            >
              Mark all reviewed
            </Button>
          )}
          {confirm && (
            <ConfirmDialog
              heading="Review signup changes"
              text={`Mark ${confirm.length} signup changes reviewed? They'll stay in the audit history.`}
              confirmLabel="Mark all reviewed"
              onCancel={() => setConfirm(null)}
              onConfirm={() => {
                const selected = confirm;
                setConfirm(null);
                void activity.review(selected);
              }}
            >
              <ul>
                {confirm.map((item) => (
                  <li key={item.id}>{item.player_name}</li>
                ))}
              </ul>
            </ConfirmDialog>
          )}
        </ActionPanel>
      )}
    </div>
  );
}

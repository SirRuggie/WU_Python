import { formatNumber } from "../format";
import { StatusPill } from "../rosterUi/primitives";
import {
  canApply,
  clanSection,
  type ReturnAction,
  type ReturnClan,
} from "./model";

export default function ReturnReminderStatus({
  clans,
  loading,
  error,
  busy,
  onAction,
}: {
  clans: ReturnClan[];
  loading: boolean;
  error: string;
  busy: boolean;
  onAction: (action: ReturnAction, clans: ReturnClan[]) => void;
}) {
  const automatic = clans.filter((clan) => clanSection(clan) === "FWA");
  const scheduled = automatic.filter(
    (clan) => clan.return_status?.state === "scheduled",
  );
  const paused = automatic.filter(
    (clan) => clan.return_status?.state === "paused",
  );
  const running = scheduled.filter(
    (clan) => clan.return_status?.label === "Running",
  );
  const action = scheduled.length ? "pause" : "resume";
  const targets = (action === "pause" ? scheduled : paused).filter((clan) =>
    canApply(clan, action),
  );
  const unavailable = loading || !!error;
  return (
    <div
      className="return-scheduling-status"
      aria-label="Automatic FWA reminders"
    >
      <StatusPill
        tone={
          unavailable
            ? "neutral"
            : scheduled.length
              ? "success"
              : paused.length
                ? "warning"
                : "neutral"
        }
      >
        {loading
          ? "Loading…"
          : error
            ? "Status unavailable"
            : scheduled.length
              ? "On"
              : paused.length
                ? "Paused"
                : "Off"}
      </StatusPill>
      {!unavailable && scheduled.length > 0 && (
        <span> · {formatNumber(running.length)} running</span>
      )}
      <button
        type="button"
        disabled={unavailable || busy || !targets.length || targets.length > 50}
        aria-label={`${action === "pause" ? "Pause" : "Resume"} return reminders for all eligible FWA clans`}
        onClick={() => onAction(action, targets)}
      >
        {action === "pause" ? "Pause" : "Resume"}
      </button>
      {targets.length > 50 && (
        <span className="small">
          Use Clans to review up to 50 clans at a time.
        </span>
      )}
    </div>
  );
}

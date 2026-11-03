import { shortReminderTime } from "./SignupReminderOverview";
import {
  reminderHistoryDetail,
  reminderHistoryStatus,
  reminderHistoryTitle,
} from "./reminderHistory";

export default function ReminderDeliveryHistory({
  history,
}: {
  history?: Record<string, unknown>[];
}) {
  if (!Array.isArray(history)) return <p>Delivery history unavailable.</p>;
  if (!history.length)
    return <p>No recorded delivery activity for this CWL month.</p>;
  return (
    <>
      {history.slice(0, 30).map((value, index) => {
        const entry =
          value && typeof value === "object" && !Array.isArray(value)
            ? value
            : {};
        const stamp = [entry.at, entry.sent_at, entry.updated_at].find(
          (time): time is string =>
            typeof time === "string" && Number.isFinite(Date.parse(time)),
        );
        const detail = reminderHistoryDetail(entry);
        return (
          <div className="reminder-history-row" key={index}>
            <strong>{reminderHistoryTitle(entry)}</strong>
            <span>{reminderHistoryStatus(entry)}</span>
            <small>
              {stamp ? (
                <time dateTime={stamp}>{shortReminderTime(stamp)}</time>
              ) : (
                "Time unavailable"
              )}
            </small>
            {detail && (
              <small>
                {"scheduled" in detail
                  ? `Scheduled ${shortReminderTime(detail.scheduled)}`
                  : detail.reason}
              </small>
            )}
          </div>
        );
      })}
    </>
  );
}

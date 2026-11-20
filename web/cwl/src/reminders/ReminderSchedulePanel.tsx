import type { Campaign, CampaignState, Occurrence } from "../reminderCampaign";
import { shortReminderTime, reminderStatusLabel } from "./reminderFormat";

export default function ReminderSchedulePanel({
  draft,
  preview,
  schedule,
  sentOccurrences,
  skipped,
  timeZone,
}: {
  draft: Campaign;
  preview: CampaignState | null;
  schedule: Occurrence[];
  sentOccurrences: string[] | undefined;
  skipped: string[] | undefined;
  timeZone?: string;
}) {
  return (
    <details
      className="reminder-disclosure reminder-schedule-panel"
      key={preview ? "preview" : "saved"}
      open={!!preview}
    >
      <summary>
        {preview ? "Review schedule changes" : "View saved schedule"}
      </summary>
      {(preview?.protected_sent?.length || 0) > 0 && (
        <p className="notice">Already sent messages will not be sent again.</p>
      )}
      <div className="reminder-schedule">
        {schedule
          .filter((item) => item.message_id !== "roster")
          .map((item) => (
            <div key={item.id}>
              <strong>
                {draft.messages[item.message_id]?.label || item.message_id}
              </strong>
              <span>{item.variant === "main" ? "Main" : "Lazy"}</span>
              <time>{shortReminderTime(item.run_at, timeZone)}</time>
              <small>
                {reminderStatusLabel(
                  item.status ||
                    (sentOccurrences?.includes(item.id)
                      ? "sent"
                      : skipped?.includes(item.id)
                        ? "skipped"
                        : draft.paused
                          ? "paused"
                          : item.run_at && new Date(item.run_at) > new Date()
                            ? "pending"
                            : "uncertain"),
                )}
              </small>
            </div>
          ))}
      </div>
      {!schedule.length && <p>No enabled scheduled messages.</p>}
    </details>
  );
}

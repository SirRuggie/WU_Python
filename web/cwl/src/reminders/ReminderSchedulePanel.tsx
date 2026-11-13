import type { Campaign, CampaignState, Occurrence } from "../reminderCampaign";
import { shortReminderTime } from "./SignupReminderOverview";

export default function ReminderSchedulePanel({
  draft,
  preview,
  schedule,
  sentOccurrences,
  skipped,
}: {
  draft: Campaign;
  preview: CampaignState | null;
  schedule: Occurrence[];
  sentOccurrences: string[] | undefined;
  skipped: string[] | undefined;
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
      <p>
        Times below use your browser timezone. Schedule timezone:{" "}
        {draft.timezone}.
      </p>
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
              <time>{shortReminderTime(item.run_at)}</time>
              <small>
                {item.status ||
                  (sentOccurrences?.includes(item.id)
                    ? "Sent"
                    : skipped?.includes(item.id)
                      ? "Skipped"
                      : draft.paused
                        ? "Paused"
                        : item.run_at && new Date(item.run_at) > new Date()
                          ? "Upcoming"
                          : "Check delivery history")}
              </small>
            </div>
          ))}
      </div>
      {!schedule.length && <p>No enabled scheduled messages.</p>}
    </details>
  );
}

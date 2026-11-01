import ConfirmDialog from "./ConfirmDialog";
import DiscordPreview from "./DiscordPreview";
import type { PingReview } from "./declarationPings";
export default function DeclarationPingReview({
  review,
  busy,
  onCancel,
  onConfirm,
}: {
  review: PingReview;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <ConfirmDialog
      heading={
        review.mode === "test"
          ? "Send a no-ping test?"
          : `Ping ${review.count} players in #${review.channel.name}?`
      }
      text={
        review.mode === "test"
          ? `Post ${review.chunks} sample messages to #${review.channel.name}. Nobody will be pinged; no ping receipt or cooldown is recorded.`
          : `Fresh arrival check: ${review.count} missing accounts. ${review.unlinked} have no linked Discord. ${review.unknown} unavailable locations excluded. ${review.chunks} messages.`
      }
      confirmLabel={review.mode === "test" ? "Send test" : "Send pings"}
      onCancel={onCancel}
      onConfirm={onConfirm}
      disabled={busy}
    >
      <div className="declaration-ping-review">
        <ul>
          {review.groups.map((g) => (
            <li key={g.tag}>
              <strong>{g.name}</strong> · {g.accounts.length} missing ·{" "}
              {g.users.length} Discord members
              {g.unlinked.length > 0 && (
                <span>
                  {" "}
                  · No linked Discord:{" "}
                  {g.unlinked.map((a) => a.name).join(", ")}
                </span>
              )}
            </li>
          ))}
        </ul>
        <details>
          <summary>Review the rendered messages</summary>
          {review.previews.map((parts, i) => (
            <DiscordPreview
              key={i}
              parts={parts}
              label={`Chunk ${i + 1} of ${review.chunks}`}
            />
          ))}
        </details>
      </div>
    </ConfirmDialog>
  );
}

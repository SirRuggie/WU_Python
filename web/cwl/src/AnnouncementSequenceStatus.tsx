import { useEffect, useRef, useState } from "react";
import { api, type Pool } from "./api";
import type { ImageSequence } from "./manageBridge";
import ConfirmDialog from "./ConfirmDialog";
import { Button } from "./rosterUi/primitives";

export default function AnnouncementSequenceStatus({
  seasonId,
  pool,
  sequence,
  canSend,
  onRefresh,
}: {
  seasonId: string;
  pool: Pool;
  sequence?: ImageSequence;
  canSend: boolean;
  onRefresh: () => Promise<void>;
}) {
  const [confirm, setConfirm] = useState<{
    sequenceId: string;
    requestId: string;
    name: string;
  } | null>(null);
  const [resumeReview, setResumeReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const running = useRef(false);
  const mounted = useRef(true);
  const permission = useRef(canSend);
  permission.current = canSend;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!canSend) {
      setConfirm(null);
      setResumeReview(false);
    }
  }, [canSend]);
  if (!sequence?.sequence_id || sequence.status === "not_started") return null;
  const sent = sequence.clans.filter((clan) => clan.status === "posted").length;
  const stopped = sequence.clans.find((clan) => clan.status !== "posted");
  const unknownClan = sequence.clans.find((clan) =>
    ["sending", "uncertain"].includes(clan.status),
  );
  const unknownClosing =
    sequence.closing &&
    ["sending", "uncertain"].includes(sequence.closing.status);
  const unknown = unknownClan?.request_id
    ? { requestId: unknownClan.request_id, name: unknownClan.name }
    : unknownClosing
      ? { requestId: sequence.closing!.request_id, name: "closing note" }
      : null;
  async function action(
    kind: "resume" | "recover",
    sequenceId: string,
    requestId?: string,
  ) {
    if (!permission.current || running.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    setConfirm(null);
    try {
      await api(
        `/seasons/${encodeURIComponent(seasonId)}/manage-bridge/${pool}/sequence/${kind}`,
        "POST",
        kind === "resume"
          ? { sequence_id: sequenceId }
          : {
              sequence_id: sequenceId,
              request_id: requestId,
              confirm_duplicate: true,
            },
      );
      if (mounted.current) await onRefresh();
    } catch (caught) {
      if (mounted.current)
        setError(
          caught instanceof Error
            ? caught.message
            : "Could not continue the post. Refresh status.",
        );
    } finally {
      running.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  return (
    <div className="announcement-sequence">
      <p role="status">
        {sequence.status === "complete"
          ? "Clan images and closing note posted"
          : sequence.status === "awaiting_announcement"
            ? "Images wait for the announcement to be confirmed"
            : sequence.status === "stopped"
              ? sequence.announcement_confirmed
                ? `Stopped at ${stopped?.name || "closing note"}`
                : "Stopped before the announcement was confirmed"
              : `Posting clan images · ${sent} of ${sequence.clans.length}`}
      </p>
      {sequence.status === "complete" && sequence.closing?.error && (
        <p>{sequence.closing.error}</p>
      )}
      {sequence.status === "stopped" && sequence.error && (
        <p className="notice error">{sequence.error}</p>
      )}
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {canSend &&
        sequence.status === "stopped" &&
        sequence.announcement_confirmed &&
        (unknown ? (
          <Button
            disabled={busy}
            onClick={() =>
              setConfirm({ sequenceId: sequence.sequence_id!, ...unknown })
            }
          >
            Check first
          </Button>
        ) : (
          <Button disabled={busy} onClick={() => setResumeReview(true)}>
            Resume
          </Button>
        ))}
      {resumeReview && (
        <ConfirmDialog
          heading="Resume clan images"
          text={`Continue with ${stopped?.name || "the closing note"}? The announcement will not be posted or pinged again.`}
          confirmLabel="Resume"
          onCancel={() => setResumeReview(false)}
          onConfirm={() => {
            setResumeReview(false);
            void action("resume", sequence.sequence_id!);
          }}
        />
      )}
      {confirm && (
        <ConfirmDialog
          heading="Check Discord first"
          text={`${confirm.name} may already have posted. Check the channel before continuing. Posting again may create a duplicate.`}
          confirmLabel="Post again anyway"
          onCancel={() => setConfirm(null)}
          onConfirm={() =>
            void action("recover", confirm.sequenceId, confirm.requestId)
          }
        />
      )}
    </div>
  );
}

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
  announcementSent = false,
  channelName = "the reviewed channel",
  onRefresh,
}: {
  seasonId: string;
  pool: Pool;
  sequence?: ImageSequence;
  canSend: boolean;
  announcementSent?: boolean;
  channelName?: string;
  onRefresh: () => Promise<void>;
}) {
  const [confirm, setConfirm] = useState<{
    sequenceId: string;
    requestId: string;
    name: string;
  } | null>(null);
  const [assumeReview, setAssumeReview] = useState(false);
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
      setAssumeReview(false);
    }
  }, [canSend]);
  useEffect(() => {
    setAssumeReview(false);
    setResumeReview(false);
    setConfirm(null);
  }, [sequence?.sequence_id, sequence?.version, sequence?.channel_id]);
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
    kind: "resume" | "recover" | "assume",
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
        kind === "assume"
          ? {
              sequence_id: sequenceId,
              version: sequence?.version,
              channel_id: sequence?.channel_id,
              confirm_no_pings: true,
            }
          : kind === "resume"
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
      {canSend &&
        announcementSent &&
        !sequence.announcement_confirmed &&
        ["stopped", "awaiting_announcement"].includes(sequence.status) && (
          <>
            <p>
              Announcement shows as sent, but its message couldn't be confirmed.
            </p>
            <Button disabled={busy} onClick={() => setAssumeReview(true)}>
              Post clan images now
            </Button>
          </>
        )}
      {assumeReview && (
        <ConfirmDialog
          heading="Post clan images now"
          text={`Posts to ${channelName}: ${sequence.clans.length} clan images then the closing note · No pings. The announcement will not be sent again.`}
          confirmLabel="Post clan images now"
          disabled={busy}
          onCancel={() => setAssumeReview(false)}
          onConfirm={() => {
            setAssumeReview(false);
            void action("assume", sequence.sequence_id!);
          }}
        >
          <ol>
            {sequence.clans.map((clan) => (
              <li key={clan.tag}>{clan.name}</li>
            ))}
          </ol>
        </ConfirmDialog>
      )}
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

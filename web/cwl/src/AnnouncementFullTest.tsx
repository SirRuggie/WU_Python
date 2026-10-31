import useAnnouncementTestChannel from "./useAnnouncementTestChannel";
import TestChannelDefault from "./TestChannelDefault";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Pool } from "./api";
import type { AnnouncementDraft } from "./announcementDrafts";
import type { AnnouncementChannel } from "./announcements";
import ChannelCombobox from "./ChannelCombobox";
import ConfirmDialog from "./ConfirmDialog";

type TestState = {
  request_id: string;
  status: string;
  next_step: number;
  steps: number;
  error: string | null;
  channel_id: string;
  message_url?: string | null;
};
export default function AnnouncementFullTest({
  seasonId,
  pool,
  version,
  generation,
  draft,
  channels,
  allowed,
  clanNames,
}: {
  seasonId: string;
  pool: Pool;
  version: number | null;
  generation: string;
  draft: AnnouncementDraft;
  channels: AnnouncementChannel[];
  allowed: boolean;
  clanNames: string[];
}) {
  const destination = useAnnouncementTestChannel(allowed);
  const { channel, setChannel } = destination;
  const [review, setReview] = useState(false);
  const [job, setJob] = useState<TestState | null>(null);
  const [showResult, setShowResult] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const permission = useRef(allowed);
  permission.current = allowed;
  const running = useRef(false);
  const pendingRequest = useRef<Record<string, unknown> | null>(null);
  const alive = useRef(true);
  const identity = useRef("");
  identity.current = `${seasonId}:${pool}:${version}:${generation}`;
  const base = `/seasons/${encodeURIComponent(seasonId)}/manage-bridge/${pool}/test-full`;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!allowed) {
      setReview(false);
      setShowResult(false);
      setJob(null);
    }
  }, [allowed]);
  useEffect(() => {
    if (!allowed || !job || !["ready", "sending"].includes(job.status)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (document.visibilityState === "hidden") {
        timer = setTimeout(poll, 2000);
        return;
      }
      try {
        const result = await api<{ test: TestState }>(
          `${base}/${job.request_id}`,
        );
        if (stopped) return;
        setJob(result.test);
        if (["ready", "sending"].includes(result.test.status))
          timer = setTimeout(poll, 2000);
      } catch (e) {
        if (!stopped) setError((e as Error).message);
      }
    };
    timer = setTimeout(poll, 1000);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [allowed, base, job?.request_id, job?.status]);
  async function send() {
    if (!allowed || !version || !channel || running.current) return;
    const reviewedIdentity = identity.current;
    running.current = true;
    setBusy(true);
    setReview(false);
    setError("");
    if (!pendingRequest.current)
      pendingRequest.current = {
        channel_id: channel,
        request_id: crypto.randomUUID().replaceAll("-", "").slice(0, 24),
        generation,
        version,
        body: draft.body,
        roster_url: draft.roster_url,
      };
    try {
      await destination.saveDefault();
      if (
        !alive.current ||
        !permission.current ||
        reviewedIdentity !== identity.current
      )
        return;
      const result = await api<{ test: TestState }>(
        base,
        "POST",
        pendingRequest.current,
      );
      pendingRequest.current = null;
      if (alive.current) {
        setJob(result.test);
        setShowResult(true);
        setNotice("");
      }
    } catch (e) {
      if (
        e instanceof ApiError &&
        e.status >= 400 &&
        e.status < 500 &&
        e.status !== 408
      )
        pendingRequest.current = null;
      if (alive.current) setError((e as Error).message);
    } finally {
      running.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const active = !!job && ["ready", "sending"].includes(job.status);
  const channelName =
    channels.find((c) => c.id === (job?.channel_id || channel))?.name ||
    job?.channel_id ||
    channel;
  function closeResult() {
    setShowResult(false);
    setNotice(
      job?.status === "complete"
        ? `Test posted to #${channelName} · no pings`
        : "Test status is shown below.",
    );
  }
  return (
    <details className="announcement-test">
      <summary>Test full post · no pings</summary>
      <p>
        The announcement, clan images in order, then a closing note. Does not
        mark announcements as sent.
      </p>
      <ChannelCombobox
        label="Full test channel"
        channels={channels}
        value={channel}
        disabled={
          !allowed ||
          busy ||
          active ||
          !!pendingRequest.current ||
          job?.status === "uncertain"
        }
        onChange={setChannel}
      />
      <TestChannelDefault
        checked={destination.makeDefault}
        disabled={busy || !allowed}
        error={destination.error}
        onChange={destination.setMakeDefault}
        onReload={destination.reload}
      />
      <button
        disabled={!allowed || !version || !channel || busy || active}
        onClick={() => setReview(true)}
      >
        Test full post
      </button>
      {!version && <p>Publish a roster before testing its images.</p>}
      {job && (
        <p role="status">
          {job.status === "complete"
            ? "Full test complete"
            : job.status === "uncertain"
              ? "Check Discord before another test"
              : job.status === "failed"
                ? "Full test stopped"
                : `Testing · ${job.next_step} of ${job.steps} messages confirmed`}
          {job.error ? ` · ${job.error}` : ""}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {error && <p role="alert">{error}</p>}
      {showResult && job && (
        <ConfirmDialog
          heading={
            job.status === "complete"
              ? "Done"
              : active
                ? "Posting test"
                : "Test stopped"
          }
          text={
            job.status === "complete"
              ? `TEST posted to #${channelName} · no pings · 1 announcement, ${Math.max(0, job.steps - 2)} clan images and the closing note.`
              : active
                ? `Posting ${Math.min(job.next_step + 1, job.steps)} of ${job.steps} messages to #${channelName}…`
                : `Stopped after ${job.next_step} of ${job.steps} messages. ${job.error || "Check Discord before another test; delivery may be uncertain."}`
          }
          confirmLabel="Close"
          hideCancel
          onConfirm={closeResult}
          onCancel={closeResult}
        >
          {job.message_url &&
            /^https:\/\/discord\.com\/channels\/\d+\/\d+\/\d+$/.test(
              job.message_url,
            ) && (
              <a
                className="announcement-result-link"
                href={job.message_url}
                target="_blank"
                rel="noreferrer"
              >
                Open in Discord
              </a>
            )}
        </ConfirmDialog>
      )}
      {review && (
        <ConfirmDialog
          heading="Test full post"
          text={`${job?.status === "uncertain" || error ? "Check Discord first: an earlier test may already have posted. Sending another can duplicate it. " : ""}Send 1 announcement, ${clanNames.length} clan images (${clanNames.join(", ") || "none"}), then a closing note to #${channels.find((c) => c.id === channel)?.name || channel}? No pings. Production sent marks stay unchanged.`}
          confirmLabel="Send full test"
          onConfirm={() => void send()}
          onCancel={() => setReview(false)}
        />
      )}
    </details>
  );
}

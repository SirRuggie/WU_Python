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
  const [channel, setChannel] = useState("");
  const [review, setReview] = useState(false);
  const [job, setJob] = useState<TestState | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const pendingRequest = useRef<Record<string, unknown> | null>(null);
  const alive = useRef(true);
  const base = `/seasons/${encodeURIComponent(seasonId)}/manage-bridge/${pool}/test-full`;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!allowed) setReview(false);
  }, [allowed]);
  useEffect(() => {
    if (!allowed || !job || !["ready", "sending"].includes(job.status)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
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
      const result = await api<{ test: TestState }>(
        base,
        "POST",
        pendingRequest.current,
      );
      pendingRequest.current = null;
      if (alive.current) setJob(result.test);
    } catch (e) {
      if (e instanceof ApiError && e.status >= 400 && e.status < 500 && e.status !== 408)
        pendingRequest.current = null;
      if (alive.current) setError((e as Error).message);
    } finally {
      running.current = false;
      if (alive.current) setBusy(false);
    }
  }
  const active = !!job && ["ready", "sending"].includes(job.status);
  return (
    <details className="announcement-test">
      <summary>Test full post · no pings</summary>
      <p>
        TEST announcement, clan images in order, then a closing note. Does not
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
      {error && <p role="alert">{error}</p>}
      {review && (
        <ConfirmDialog
          heading="Test full post"
          text={`${job?.status === "uncertain" || error ? "Check Discord first: an earlier test may already have posted. Sending another can duplicate it. " : ""}Send 1 TEST announcement, ${clanNames.length} clan images (${clanNames.join(", ") || "none"}), then a closing note to #${channels.find((c) => c.id === channel)?.name || channel}? No pings. Production sent marks stay unchanged.`}
          confirmLabel="Send full test"
          onConfirm={() => void send()}
          onCancel={() => setReview(false)}
        />
      )}
    </details>
  );
}

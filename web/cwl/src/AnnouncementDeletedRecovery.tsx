import { createPortal } from "react-dom";
import { AnnouncementMoreContext } from "./AnnouncementPoolCard";
import { useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, type Pool } from "./api";
import AnnouncementSendReview from "./AnnouncementSendReview";
import type { ImageSequence } from "./manageBridge";
import { Button } from "./rosterUi/primitives";

type Props = {
  seasonId: string;
  pool: Pool;
  cycle: string;
  version: number | null;
  generation: string;
  channel: string;
  channelName: string;
  roleNames: string[];
  clans: ImageSequence["clans"];
  preview: ReactNode;
  allowed: boolean;
  onQueued: () => void;
  onDeleted?: (deleted: boolean) => void;
};
export default function AnnouncementDeletedRecovery(props: Props) {
  const moreTarget = useContext(AnnouncementMoreContext);
  const [deleted, setDeleted] = useState<string | null>(null);
  const checked = useRef({ identity: "", at: 0 });
  const [review, setReview] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const reviewedIdentity = useRef("");
  const alive = useRef(true);
  const latest = useRef(props);
  latest.current = props;
  const identity = `${props.seasonId}:${props.pool}:${props.generation}:${props.version}:${props.channel}`;
  const currentIdentity = useRef(identity);
  currentIdentity.current = identity;
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    setReview(null);
    setNotice("");
    setDeleted(null);
    props.onDeleted?.(false);
  }, [identity]);
  useEffect(() => {
    if (!props.allowed) setReview(null);
  }, [props.allowed]);
  useEffect(() => {
    if (props.allowed && !busy && checked.current.identity !== identity)
      void check();
  }, [identity, props.allowed, busy]);
  const valid = (captured: string) =>
    alive.current &&
    latest.current.allowed &&
    currentIdentity.current === captured;
  const base = `/seasons/${encodeURIComponent(props.seasonId)}/manage-bridge/${props.pool}`;
  const check = async () => {
    if (running.current || !props.allowed) return;
    if (
      checked.current.identity === identity &&
      Date.now() - checked.current.at < 30000
    ) {
      setNotice("Checked moments ago");
      return;
    }
    checked.current = { identity, at: Date.now() };
    running.current = true;
    setBusy(true);
    setNotice("");
    const captured = identity;
    try {
      const result = await api<{ deleted: boolean; message_id: string }>(
        `${base}/check-message`,
      );
      if (!valid(captured)) return;
      props.onDeleted?.(result.deleted);
      if (result.deleted) {
        reviewedIdentity.current = captured;
        setDeleted(result.message_id);
      } else {
        setDeleted(null);
        setNotice("The announcement still exists in Discord.");
      }
    } catch (error) {
      if (valid(captured))
        setNotice(
          error instanceof Error
            ? error.message
            : "Could not verify the message. Nothing was sent.",
        );
    } finally {
      running.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const resend = async () => {
    if (
      running.current ||
      !review ||
      !props.allowed ||
      !props.version ||
      reviewedIdentity.current !== identity
    )
      return;
    const captured = identity,
      message = review;
    running.current = true;
    setBusy(true);
    setReview(null);
    setNotice("");
    try {
      await api(`${base}/send`, "POST", {
        generation: props.generation,
        channel_id: props.channel,
        version: props.version,
        deleted_message_id: message,
        confirm_resend: true,
      });
      if (valid(captured)) {
        setNotice("Announcement and images queued.");
        props.onQueued();
      }
    } catch (error) {
      if (valid(captured))
        setNotice(
          error instanceof Error
            ? error.message
            : "Could not confirm the queue. Refresh status before retrying.",
        );
    } finally {
      running.current = false;
      if (alive.current) setBusy(false);
    }
  };
  const checkButton = (
    <Button disabled={!props.allowed || busy} onClick={() => void check()}>
      Check posted message
    </Button>
  );
  return (
    <>
      {moreTarget ? createPortal(checkButton, moreTarget) : checkButton}
      {deleted && (
        <>
          <p role="status">Previous post was deleted</p>
          <Button
            disabled={!props.allowed || busy}
            onClick={() => setReview(deleted)}
          >
            Send again
          </Button>
        </>
      )}
      {notice && <p role="status">{notice}</p>}
      {review && props.allowed && (
        <AnnouncementSendReview
          cycle={props.cycle}
          version={props.version}
          pools={[
            {
              key: props.pool,
              label: props.pool === "lazy" ? "Lazy" : "Main",
              destination: props.channelName,
              roleNames: props.roleNames,
              clans: props.clans,
              preview: props.preview,
              resend: true,
            },
          ]}
          onCancel={() => setReview(null)}
          onConfirm={() => void resend()}
        />
      )}
    </>
  );
}

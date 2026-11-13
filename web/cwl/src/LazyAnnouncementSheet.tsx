import { lazy, Suspense, useEffect, useRef, useState } from "react";
import ActionPanel from "./ActionPanel";
import ChannelCombobox from "./ChannelCombobox";
import { api, ApiError } from "./api";
import type { AnnouncementChannel } from "./announcements";
import { exportMonthLabel } from "./exportPreview";
import LoadError from "./LoadError";
import {
  loadLazyAnnouncement,
  newRequestId,
  sendLazyAnnouncement,
  type LazyAnnouncementPreview,
  type LazyAnnouncementResult,
  type LazyAnnouncementScope,
} from "./lazyAnnouncement";
import "./LazyAnnouncement.css";

const DiscordPreview = lazy(() => import("./DiscordPreview"));

type Props = {
  seasonId: string;
  clans: { tag: string; name: string }[];
  /** The Lazy clan open in the page, if any. */
  initialClan: string;
  archived: boolean;
  trigger: HTMLElement | null;
  onClose: () => void;
  onSent: () => void;
};

const errorText = (cause: unknown, fallback: string) =>
  cause instanceof Error && cause.message ? cause.message : fallback;

const plural = (count: number, word: string) =>
  `${count} ${word}${count === 1 ? "" : "s"}`;

export default function LazyAnnouncementSheet({
  seasonId,
  clans,
  initialClan,
  archived,
  trigger,
  onClose,
  onSent,
}: Props) {
  const [scope, setScope] = useState<LazyAnnouncementScope>(
    initialClan ? "one" : "all",
  );
  const [clan, setClan] = useState(initialClan || clans[0]?.tag || "");
  const [ping, setPing] = useState(true);
  const [channels, setChannels] = useState<AnnouncementChannel[]>([]);
  const [channelsError, setChannelsError] = useState("");
  const [channelsTry, setChannelsTry] = useState(0);
  const [channel, setChannel] = useState("");
  const [preview, setPreview] = useState<LazyAnnouncementPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [previewTry, setPreviewTry] = useState(0);
  const [loading, setLoading] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [result, setResult] = useState<LazyAnnouncementResult | null>(null);
  const [stale, setStale] = useState(false);
  // One ID per Send. A retry after a lost response reuses it, so the server
  // returns the first result instead of posting again.
  const requestId = useRef(newRequestId());
  const inFlight = useRef(false);

  useEffect(() => {
    let active = true;
    setChannelsError("");
    api<{ channels: AnnouncementChannel[] }>("/announcement-channels")
      .then((data) => active && setChannels(data.channels))
      .catch(
        (cause) =>
          active &&
          setChannelsError(errorText(cause, "Channels did not load.")),
      );
    return () => {
      active = false;
    };
  }, [channelsTry]);

  useEffect(() => {
    if (scope === "one" && !clan) return;
    const controller = new AbortController();
    setLoading(true);
    setPreviewError("");
    setReviewed(false);
    setSendError("");
    setStale(false);
    requestId.current = newRequestId();
    loadLazyAnnouncement(seasonId, scope, clan, ping, controller.signal)
      .then((data) => setPreview(data))
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setPreview(null);
        setPreviewError(errorText(cause, "The preview did not load."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [seasonId, scope, clan, ping, previewTry]);

  const channelName = channels.find((c) => c.id === channel)?.name;
  const blocked =
    !preview || preview.blockers.length > 0 || !preview.pages.length;
  const canSend =
    !archived && !loading && !sending && !blocked && !!channelName && reviewed;
  const locked = sending || !!result;

  async function send() {
    // The ref blocks a second tap before React re-renders the disabled button.
    if (!preview || !canSend || inFlight.current) return;
    inFlight.current = true;
    setSending(true);
    setSendError("");
    try {
      const sent = await sendLazyAnnouncement(
        seasonId,
        preview,
        channel,
        requestId.current,
      );
      setResult(sent);
      onSent();
    } catch (cause) {
      // Keep the same ID: a retry returns the first result and never posts twice.
      setSendError(errorText(cause, "Send status is unknown. Check Discord."));
      setStale(cause instanceof ApiError && cause.status === 409);
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }

  function sendAnother() {
    setResult(null);
    setSendError("");
    setReviewed(false);
    requestId.current = newRequestId();
  }

  const summary = preview && (
    <p className="lazy-announce-summary">
      {preview.cycle && <strong>{exportMonthLabel(preview.cycle)}</strong>}
      {preview.cycle && " · "}
      {plural(preview.clan_count, "clan")}
      {" · "}
      {plural(preview.winner_count, "winner")}
      {" · "}
      {plural(preview.pages.length, "message")}
    </p>
  );

  const footer = result ? (
    <div className="lazy-announce-footer">
      <button type="button" onClick={sendAnother}>
        Send again
      </button>
      <button type="button" className="primary" onClick={onClose}>
        Done
      </button>
    </div>
  ) : (
    <div className="lazy-announce-footer">
      <button type="button" disabled={sending} onClick={onClose}>
        Cancel
      </button>
      <button
        type="button"
        className="primary"
        disabled={!canSend}
        onClick={() => void send()}
      >
        {sending
          ? "Sending…"
          : channelName
            ? `Send to #${channelName}`
            : "Send announcement"}
      </button>
    </div>
  );

  return (
    <ActionPanel
      title="Lazy bonus announcement"
      className="lazy-announce roster-ui"
      trigger={trigger}
      busy={sending}
      onClose={() => {
        if (sending) return false;
        onClose();
      }}
      footer={footer}
    >
      {archived && <p className="notice">Archived season · Read only</p>}
      {result ? (
        <section className="lazy-announce-result" aria-live="polite">
          <p
            className={`notice lazy-announce-status${result.status === "sent" ? " success" : result.status === "failed" ? " error" : ""}`}
            role={result.status === "sent" ? "status" : "alert"}
          >
            <strong>
              {result.status === "sent"
                ? "Announcement sent"
                : result.status === "failed"
                  ? "Not sent"
                  : "Send status unknown"}
            </strong>
            {result.failure && <span> · {result.failure}</span>}
          </p>
          <p className="small">
            {result.urls.length} of {plural(result.pages, "message")} confirmed
          </p>
          {result.urls.map((link, index) => (
            <p key={link}>
              <a href={link} target="_blank" rel="noreferrer">
                View message {index + 1} in Discord ↗
              </a>
            </p>
          ))}
        </section>
      ) : (
        <>
          <fieldset className="lazy-announce-scope" disabled={locked}>
            <legend>Clans</legend>
            <div className="lazy-announce-segments">
              {(
                [
                  ["all", "All Lazy clans"],
                  ["one", "One clan"],
                ] as const
              ).map(([value, label]) => (
                <label
                  key={value}
                  className={scope === value ? "selected" : ""}
                >
                  <input
                    type="radio"
                    name="lazy-announce-scope"
                    value={value}
                    checked={scope === value}
                    onChange={() => setScope(value)}
                  />
                  <span>{label}</span>
                </label>
              ))}
            </div>
            {scope === "one" && (
              <label className="lazy-announce-field">
                Clan
                <select
                  name="lazy-announce-clan"
                  value={clan}
                  onChange={(event) => setClan(event.target.value)}
                >
                  {clans.map((item) => (
                    <option key={item.tag} value={item.tag}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </fieldset>

          {loading && <p role="status">Loading preview…</p>}
          {previewError && (
            <p role="alert" className="notice error">
              {previewError}{" "}
              <button type="button" onClick={() => setPreviewTry((n) => n + 1)}>
                Retry preview
              </button>
            </p>
          )}
          {preview && (
            <div
              className="lazy-announce-body"
              aria-busy={loading}
              style={{ opacity: loading ? 0.5 : 1 }}
            >
              {summary}
              {preview.blockers.length > 0 && (
                <div className="notice lazy-announce-blockers" role="alert">
                  <ul>
                    {preview.blockers.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </div>
              )}
              {preview.unlinked_count > 0 && (
                <p className="small lazy-announce-note">
                  {plural(preview.unlinked_count, "player")} with no linked
                  Discord account show by tag only.
                </p>
              )}
              {preview.pages.length > 0 && (
                <details className="lazy-announce-preview" open>
                  <summary>
                    Preview · {plural(preview.pages.length, "message")}
                  </summary>
                  {preview.pages.map((parts, index) => (
                    <Suspense key={index} fallback={<p>Loading preview…</p>}>
                      <DiscordPreview
                        label={`Message ${index + 1}`}
                        parts={parts}
                        caption={
                          preview.ping
                            ? "Pings this month's winners only. Last month's winners do not get a ping."
                            : "No pings. Player mentions do not notify."
                        }
                      />
                    </Suspense>
                  ))}
                </details>
              )}
            </div>
          )}

          <div className="lazy-announce-send">
            <ChannelCombobox
              label="Channel"
              channels={channels}
              value={channel}
              disabled={locked || archived}
              onChange={(value) => {
                setChannel(value);
                setReviewed(false);
              }}
            />
            {channelsError && (
              <LoadError
                message={channelsError}
                onRetry={() => setChannelsTry((n) => n + 1)}
              />
            )}
            <label className="bonus-check">
              <input
                type="checkbox"
                checked={ping}
                disabled={locked || archived}
                onChange={(event) => setPing(event.target.checked)}
              />
              <span>
                Ping this month's winners
                {preview?.ping && ` (${preview.ping_count})`}
              </span>
            </label>
            <label className="bonus-check">
              <input
                type="checkbox"
                checked={reviewed}
                disabled={locked || archived || blocked || !channelName}
                onChange={(event) => setReviewed(event.target.checked)}
              />
              <span>I reviewed the preview and the channel.</span>
            </label>
            {sendError && (
              <p role="alert" className="notice error">
                {sendError}
                {stale && (
                  <>
                    {" "}
                    <button
                      type="button"
                      onClick={() => setPreviewTry((n) => n + 1)}
                    >
                      Refresh preview
                    </button>
                  </>
                )}
              </p>
            )}
          </div>
        </>
      )}
    </ActionPanel>
  );
}

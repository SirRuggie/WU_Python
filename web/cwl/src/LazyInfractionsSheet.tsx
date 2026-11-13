import { lazy, Suspense, useEffect, useRef, useState } from "react";
import ActionPanel from "./ActionPanel";
import AccountCard from "./AccountCard";
import ChannelCombobox from "./ChannelCombobox";
import { api, ApiError } from "./api";
import type { AnnouncementChannel } from "./announcements";
import { newRequestId } from "./lazyAnnouncement";
import {
  loadLazyInfractions,
  sendLazyInfractions,
  type LazyInfractionPlayer,
  type LazyInfractionsPreview,
  type LazyInfractionsResult,
} from "./lazyInfractions";
import { Chip } from "./rosterUi/primitives";
import "./BonusWorkspace.css";
import "./LazyAnnouncement.css";

const DiscordPreview = lazy(() => import("./DiscordPreview"));

type Props = {
  seasonId: string;
  archived: boolean;
  /** Send CWL announcements grant; without it the sheet is a read-only list. */
  canSend: boolean;
  trigger: HTMLElement | null;
  onClose: () => void;
};

const errorText = (cause: unknown, fallback: string) =>
  cause instanceof Error && cause.message ? cause.message : fallback;

const plural = (count: number, word: string) =>
  `${count} ${word}${count === 1 ? "" : "s"}`;

function PlayerCard({
  player,
  extra,
}: {
  player: LazyInfractionPlayer;
  extra?: string;
}) {
  return (
    <AccountCard
      className="lazy-infraction-card account-card-plain"
      thLevel={player.town_hall}
      name={player.player_name || "Unknown player"}
      meta={[player.tag, extra]}
      flags={player.infractions.map((label) => (
        <Chip key={label} tone="danger">
          {label}
        </Chip>
      ))}
    />
  );
}

/** Lazy tab: every player with an infraction, grouped by clan, and the red post. */
export default function LazyInfractionsSheet({
  seasonId,
  archived,
  canSend,
  trigger,
  onClose,
}: Props) {
  const [channels, setChannels] = useState<AnnouncementChannel[]>([]);
  const [channelsError, setChannelsError] = useState("");
  const [channelsTry, setChannelsTry] = useState(0);
  const [channel, setChannel] = useState("");
  const [preview, setPreview] = useState<LazyInfractionsPreview | null>(null);
  const [previewError, setPreviewError] = useState("");
  const [previewTry, setPreviewTry] = useState(0);
  const [loading, setLoading] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState("");
  const [result, setResult] = useState<LazyInfractionsResult | null>(null);
  const [stale, setStale] = useState(false);
  // One ID per Send. A retry after a lost response reuses it, so the server
  // returns the first result instead of posting again.
  const requestId = useRef(newRequestId());
  const inFlight = useRef(false);
  const sendable = canSend && !archived;

  useEffect(() => {
    if (!sendable) return;
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
  }, [channelsTry, sendable]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setPreviewError("");
    setReviewed(false);
    setSendError("");
    setStale(false);
    requestId.current = newRequestId();
    loadLazyInfractions(seasonId, controller.signal)
      .then((data) => setPreview(data))
      .catch((cause) => {
        if (controller.signal.aborted) return;
        setPreview(null);
        setPreviewError(errorText(cause, "The list did not load."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [seasonId, previewTry]);

  const channelName = channels.find((c) => c.id === channel)?.name;
  const blocked =
    !preview || preview.blockers.length > 0 || !preview.pages.length;
  const canSendNow =
    sendable && !loading && !sending && !blocked && !!channelName && reviewed;
  const locked = sending || !!result;

  async function send() {
    // The ref blocks a second tap before React re-renders the disabled button.
    if (!preview || !canSendNow || inFlight.current) return;
    inFlight.current = true;
    setSending(true);
    setSendError("");
    try {
      setResult(
        await sendLazyInfractions(
          seasonId,
          preview,
          channel,
          requestId.current,
        ),
      );
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

  const footer = result ? (
    <div className="lazy-announce-footer">
      <button type="button" onClick={sendAnother}>
        Send again
      </button>
      <button type="button" className="primary" onClick={onClose}>
        Done
      </button>
    </div>
  ) : sendable ? (
    <div className="lazy-announce-footer">
      <button type="button" disabled={sending} onClick={onClose}>
        Cancel
      </button>
      <button
        type="button"
        className="primary"
        disabled={!canSendNow}
        onClick={() => void send()}
      >
        {sending
          ? "Sending…"
          : channelName
            ? `Send to #${channelName}`
            : "Send infractions"}
      </button>
    </div>
  ) : (
    <div className="lazy-announce-footer">
      <button type="button" className="primary" onClick={onClose}>
        Close
      </button>
    </div>
  );

  return (
    <ActionPanel
      title="Lazy infractions"
      className="lazy-announce lazy-infractions roster-ui"
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
                ? "Infractions sent"
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
          {loading && <p role="status">Loading infractions…</p>}
          {previewError && (
            <p role="alert" className="notice error">
              {previewError}{" "}
              <button type="button" onClick={() => setPreviewTry((n) => n + 1)}>
                Retry
              </button>
            </p>
          )}
          {preview && (
            <div
              className="lazy-announce-body"
              aria-busy={loading}
              style={{ opacity: loading ? 0.5 : 1 }}
            >
              <p className="lazy-announce-summary">
                {preview.label && <strong>{preview.label}</strong>}
                {preview.label && " · "}
                {plural(preview.player_count, "player")}
                {" · "}
                {plural(preview.clan_count, "clan")}
              </p>
              {preview.clans.length === 0 && (
                <p className="bonus-empty">No players have infractions.</p>
              )}
              {preview.clans.map((clan) => (
                <section
                  key={clan.tag}
                  className="lazy-infractions-clan"
                  aria-label={clan.name}
                >
                  <h3>
                    <span>{clan.name}</span>
                    <small>{plural(clan.players.length, "player")}</small>
                  </h3>
                  <ul className="bonus-account-list">
                    {clan.players.map((player) => (
                      <li key={player.tag}>
                        <PlayerCard player={player} />
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
              {preview.exceptions.length > 0 && (
                <details className="bonus-secondary lazy-infractions-exceptions">
                  <summary>
                    Staff exceptions ·{" "}
                    {plural(preview.exceptions.length, "player")}, not in the
                    post
                  </summary>
                  <ul className="bonus-account-list">
                    {preview.exceptions.map((player) => (
                      <li key={player.tag}>
                        <PlayerCard
                          player={player}
                          extra={`${player.clan_name} · ${player.reason}`}
                        />
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {sendable &&
                preview.blockers.length > 0 &&
                preview.clans.length > 0 && (
                  <div className="notice lazy-announce-blockers" role="alert">
                    <ul>
                      {preview.blockers.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  </div>
                )}
              {preview.pages.length > 0 && (
                <details className="lazy-announce-preview">
                  <summary>
                    Preview post · {plural(preview.pages.length, "message")}
                  </summary>
                  {preview.pages.map((parts, index) => (
                    <Suspense key={index} fallback={<p>Loading preview…</p>}>
                      <DiscordPreview
                        label={`Message ${index + 1}`}
                        parts={parts}
                        caption="No pings."
                      />
                    </Suspense>
                  ))}
                </details>
              )}
            </div>
          )}

          {sendable && (
            <div className="lazy-announce-send">
              <ChannelCombobox
                label="Channel"
                channels={channels}
                value={channel}
                disabled={locked}
                onChange={(value) => {
                  setChannel(value);
                  setReviewed(false);
                }}
              />
              {channelsError && (
                <p role="alert" className="notice error">
                  {channelsError}{" "}
                  <button
                    type="button"
                    onClick={() => setChannelsTry((n) => n + 1)}
                  >
                    Retry channels
                  </button>
                </p>
              )}
              <label className="bonus-check">
                <input
                  type="checkbox"
                  checked={reviewed}
                  disabled={locked || blocked || !channelName}
                  onChange={(event) => setReviewed(event.target.checked)}
                />
                <span>I reviewed the players and the channel.</span>
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
                        Refresh list
                      </button>
                    </>
                  )}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </ActionPanel>
  );
}

import DiscordIdentity from "./DiscordIdentity";
import useDiscordIdentities from "./useDiscordIdentities";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import ChannelCombobox from "./ChannelCombobox";
import ConfirmDialog from "./ConfirmDialog";
import DeclarationPingReview from "./DeclarationPingReview";
import type { PingReceipt, PingReview, PingState } from "./declarationPings";
import "./DeclarationPingPanel.css";

export default function DeclarationPingPanel({
  seasonId,
  pool,
  missing,
  onDirty = () => {},
  onWorking = () => {},
}: {
  seasonId: string;
  pool: "main" | "lazy";
  missing: number;
  onDirty?: (dirty: boolean) => void;
  onWorking?: (working: boolean) => void;
}) {
  const base = `/seasons/${seasonId}/declaration-pings/${pool}`;
  const [state, setState] = useState<PingState>();
  const [channel, setChannel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState<PingReview>();
  const [closing, setClosing] = useState(false);
  const [receipt, setReceipt] = useState<PingReceipt>();
  const [clock, setClock] = useState(Date.now() / 1000);
  const receiptStatus = useRef<HTMLParagraphElement>(null);
  const generation = useRef(0),
    readSequence = useRef(0),
    locked = useRef(false),
    dirty = useRef(false);
  const active =
    state?.active || (receipt?.state === "sending" ? receipt : undefined);
  const waiting = Math.max(0, Math.ceil((state?.cooldown_until || 0) - clock));
  async function load(signal?: AbortSignal, includeChannels = true) {
    const current = generation.current;
    const sequence = ++readSequence.current;
    try {
      const value = await api<PingState>(
        base + (includeChannels ? "" : "?channels=0"),
        "GET",
        undefined,
        { signal },
      );
      if (
        current !== generation.current ||
        sequence !== readSequence.current ||
        signal?.aborted
      )
        return;
      setError("");
      setState((old) =>
        includeChannels || !value.can_send
          ? value
          : { ...value, channels: old?.channels || [], warning: old?.warning },
      );
      if (!dirty.current) setChannel(value.channel?.id || "");
      if (!value.can_send) {
        setReview(undefined);
        dirty.current = false;
        onDirty(false);
      }
    } catch (e) {
      if (
        current === generation.current &&
        sequence === readSequence.current &&
        !signal?.aborted
      ) {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          setState(undefined);
          setReview(undefined);
          setReceipt(undefined);
          dirty.current = false;
          onDirty(false);
        }
        setError(String((e as Error).message));
      }
    }
  }
  useEffect(() => {
    const abort = new AbortController();
    generation.current++;
    void load(abort.signal);
    return () => {
      abort.abort();
      generation.current++;
      onDirty(false);
      onWorking(false);
    };
  }, [base]);
  useEffect(() => {
    if (active?.state !== "sending" && !state?.test_running) return;
    let stopped = false,
      pending = false;
    const timer = setInterval(async () => {
      if (stopped || pending || document.hidden || locked.current) return;
      pending = true;
      try {
        if (receipt?.state === "sending") {
          const result = await api<{ receipt: PingReceipt }>(
            `${base}/jobs/${receipt.token}`,
          );
          if (!stopped) setReceipt(result.receipt);
        }
        if (!stopped) await load(undefined, false);
      } catch (e) {
        if (!stopped) {
          if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
            setState(undefined);
            setReview(undefined);
            setReceipt(undefined);
            setClosing(false);
            dirty.current = false;
            onDirty(false);
          }
          setError((e as Error).message);
        }
      } finally {
        pending = false;
      }
    }, 3000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [base, active?.token, active?.state, state?.test_running, receipt?.state]);
  useEffect(() => {
    if (!waiting) return;
    const timer = setInterval(() => setClock(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [waiting > 0]);
  const edited = channel !== (state?.channel?.id || "");
  const chosen = state?.channels.find((c) => c.id === channel);
  const reason =
    state?.warning ||
    (!chosen?.can_send ? chosen?.reason || "Choose an available channel" : "");
  async function mutate(run: () => Promise<void>) {
    if (locked.current) return;
    locked.current = true;
    setBusy(true);
    onWorking(true);
    setError("");
    try {
      await run();
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setState(undefined);
        setReview(undefined);
        setReceipt(undefined);
        dirty.current = false;
        onDirty(false);
      }
      setError((e as Error).message);
    } finally {
      locked.current = false;
      setBusy(false);
      onWorking(false);
    }
  }
  function choose(value: string) {
    setChannel(value);
    dirty.current = value !== (state?.channel?.id || "");
    onDirty(dirty.current);
    setReview(undefined);
  }
  async function save() {
    await mutate(async () => {
      await api(base, "PUT", {
        channel_id: channel,
        revision: state!.revision,
      });
      dirty.current = false;
      onDirty(false);
      await load();
    });
  }
  async function prepare(mode: "live" | "test") {
    await mutate(async () => {
      const next = await api<PingReview>(`${base}/preview`, "POST", {
        revision: state!.revision,
        mode,
      });
      setReview(next);
    });
  }
  async function send() {
    if (!review) return;
    const current = review;
    setReview(undefined);
    await mutate(async () => {
      const result = await api<{ receipt: PingReceipt }>(
        `${base}/send`,
        "POST",
        {
          token: current.token,
          confirm: true,
          send_again: !!state?.history.length,
        },
      );
      setReceipt(result.receipt);
      await load();
    });
    requestAnimationFrame(() =>
      receiptStatus.current?.focus({ preventScroll: true }),
    );
  }
  const last = [receipt, state?.active, state?.history[0]]
    .filter((r): r is PingReceipt => !!r)
    .sort((a, b) => b.created_at - a.created_at)[0];
  const senderProfiles = useDiscordIdentities(last ? [last.actor_id] : []);
  return (
    <section
      className="declaration-ping-panel"
      aria-label={`${pool === "main" ? "Main" : "Lazy"} declaration pings`}
    >
      <strong>Declaration pings</strong>
      {!!state?.lineup_changes?.length && (
        <div role="status">
          <p>
            Publish these changed {pool === "main" ? "Main" : "Lazy"}{" "}
            assignments before pinging:
          </p>
          <ul>
            {state.lineup_changes.map((row) => (
              <li key={row.tag}>
                {row.name} ({row.tag}): {row.published_clan || "unassigned"} →{" "}
                {row.draft_clan || "unassigned"}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!state && !error && <p role="status">Loading ping settings…</p>}
      {error && (
        <p role="alert">
          {error}{" "}
          <button disabled={busy} onClick={() => void load()}>
            Reload latest settings
          </button>
        </p>
      )}
      {state?.can_send ? (
        <>
          <div className="declaration-ping-controls">
            <ChannelCombobox
              nameOnly
              label="Ping channel"
              channels={state.channels}
              value={channel}
              disabled={busy || !!active || state.test_running}
              onChange={choose}
            />
            {edited && (
              <>
                <button
                  disabled={busy || !!active || state.test_running || !!reason}
                  onClick={() => void save()}
                >
                  Save channel
                </button>
                <button
                  disabled={busy}
                  onClick={() => choose(state.channel?.id || "")}
                >
                  Discard
                </button>
              </>
            )}
            <button
              disabled={
                busy ||
                edited ||
                !!active ||
                state.test_running ||
                !!reason ||
                waiting > 0 ||
                !!state.lineup_changes?.length ||
                missing === 0
              }
              onClick={() => void prepare("live")}
            >
              {busy
                ? "Checking…"
                : state.history.length
                  ? "Send again"
                  : `Ping ${missing} missing`}
            </button>
          </div>
          {reason && <p>{reason}</p>}
          {edited && <p>Save or discard the channel change before pinging.</p>}
          {waiting > 0 && (
            <p role="status">
              Next ping available in {Math.ceil(waiting / 60)} min.
            </p>
          )}
          <details>
            <summary>No-ping test</summary>
            <button
              disabled={
                busy || !!active || state.test_running || !state.test_channel.id
              }
              onClick={() => void prepare("test")}
            >
              Send test
            </button>
            {!state.test_channel.id && (
              <small>
                Set the shared Test channel in Announcements for a no-ping test.
              </small>
            )}
          </details>
        </>
      ) : (
        state && (
          <p>
            Posting channel:{" "}
            {state.channel ? `#${state.channel.name}` : "Not set"} · Read-only
            access
          </p>
        )
      )}
      {(active?.state === "sending" || state?.test_running) && (
        <p role="status">Sending reviewed chunks… You may leave this page.</p>
      )}
      {state?.can_send && active?.state === "uncertain" && (
        <button disabled={busy} onClick={() => setClosing(true)}>
          Close interrupted receipt
        </button>
      )}
      {closing && (
        <ConfirmDialog
          heading="Close interrupted receipt?"
          text="This sends nothing. Inspect the confirmed message IDs and the unconfirmed chunk in Discord. No chunk will be retried; a deliberate new review is required after cooldown."
          confirmLabel="Close receipt"
          onCancel={() => setClosing(false)}
          onConfirm={() => {
            setClosing(false);
            void mutate(async () => {
              await api(`${base}/close-interrupted`, "POST", {
                token: active!.token,
                confirm: true,
              });
              setReceipt(undefined);
              await load();
            });
          }}
        />
      )}
      {last && (
        <p ref={receiptStatus} tabIndex={-1} role="status">
          {last.test
            ? "No-ping test " + last.state
            : last.state === "done"
              ? "Last pinged"
              : "Delivery " + last.state}{" "}
          by{" "}
          <DiscordIdentity
            userId={last.actor_id}
            displayName={last.actor_name}
            resolvedMember={senderProfiles.members[last.actor_id] || null}
            resolving={senderProfiles.loading}
            variant="compact"
          />{" "}
          at {new Date(last.created_at * 1000).toLocaleString()} · {last.count}{" "}
          players · {last.posted.length}/{last.chunks} chunks confirmed
          {last.attempting !== null
            ? ` · chunk ${last.attempting + 1} unconfirmed`
            : ""}
          . {last.error}
        </p>
      )}
      {last && last.posted.length > 0 && (
        <details>
          <summary>Posted message IDs</summary>
          <ul>
            {last.posted.map((p) => (
              <li key={p.message_id}>
                Chunk {p.chunk + 1}: {p.message_id}
              </li>
            ))}
          </ul>
        </details>
      )}
      {review && (
        <DeclarationPingReview
          review={review}
          busy={busy}
          onCancel={() => setReview(undefined)}
          onConfirm={() => void send()}
        />
      )}
    </section>
  );
}

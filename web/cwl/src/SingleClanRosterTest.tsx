import useAnnouncementTestChannel from "./useAnnouncementTestChannel";
import TestChannelDefault from "./TestChannelDefault";
import ConfirmDialog from "./ConfirmDialog";
import { Button } from "./rosterUi/primitives";
import { RefreshCw, Send } from "lucide-react";
import { useDashboardPermission } from "./DashboardPermissions";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import ChannelCombobox from "./ChannelCombobox";
import type { AnnouncementChannel } from "./announcements";
import RosterImageCarousel from "./RosterImageCarousel";
type Clan = {
  tag: string;
  name: string;
  pool: string;
  count: number;
  pages: number;
};
type Data = { version: number; season: string; clans: Clan[] };
export default function SingleClanRosterTest({
  seasonId,
  version,
  disabled = false,
  acquire,
}: {
  seasonId: string;
  version: number | null;
  disabled?: boolean;
  acquire: () => (() => void) | null;
}) {
  const sending = useRef(false);
  const canManage = useDashboardPermission("cwl_send");
  const permission = useRef(canManage);
  permission.current = canManage;
  const [data, setData] = useState<Data | null>(null),
    [tag, setTag] = useState(""),
    [channels, setChannels] = useState<AnnouncementChannel[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [url, setUrl] = useState(""),
    [loaded, setLoaded] = useState(false),
    [nonce, setNonce] = useState("");
  const destination = useAnnouncementTestChannel(canManage);
  const { channel, setChannel } = destination;
  const [confirmTest, setConfirmTest] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const path = `/seasons/${encodeURIComponent(seasonId)}/roster-images`;
  const previousTag = useRef(tag);
  previousTag.current = tag;
  useEffect(() => {
    let active = true;
    const selected = previousTag.current;
    setConfirmTest(false);
    setNonce("");
    setData(null);
    setTag("");
    setUrl("");
    setError("");
    setLoaded(false);
    if (!version || !canManage) return;
    void Promise.all([
      api<Data>(path),
      api<{ channels: AnnouncementChannel[] }>("/announcement-channels"),
    ])
      .then(([result, choices]) => {
        if (active) {
          setData(result);
          setTag(
            result.clans.some((clan) => clan.tag === selected)
              ? selected
              : result.clans[0]?.tag || "",
          );
          setChannels(choices.channels);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [seasonId, version, refresh, canManage]);
  const clan = data?.clans.find((c) => c.tag === tag);
  function changed() {
    setLoaded(false);
    setNonce("");
    setUrl("");
    setError("");
  }
  async function send() {
    if (!canManage || !clan || !data || !channel || disabled || sending.current)
      return;
    const release = acquire();
    if (!release) return;
    sending.current = true;
    setConfirmTest(false);
    setBusy(true);
    setError("");
    setUrl("");
    const id =
      nonce ||
      Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("");
    setNonce(id);
    try {
      await destination.saveDefault();
      if (!permission.current) return;
      const result = await api<{ url: string }>(
        `${path}/${encodeURIComponent(tag)}/test`,
        "POST",
        { version: data.version, channel_id: channel, request_id: id },
      );
      setUrl(result.url);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Could not send test. Check Discord before retrying.",
      );
    } finally {
      sending.current = false;
      release();
      setBusy(false);
    }
  }
  return (
    <section className="clan-roster-images roster-ui">
      <div className="card-heading">
        <h3>Single-clan test</h3>
        <Button
          icon={RefreshCw}
          disabled={!canManage || busy || disabled}
          onClick={() => setRefresh((n) => n + 1)}
        >
          Refresh images
        </Button>
      </div>
      <p>Choose a clan, preview its finalized roster, then send a test.</p>
      {!version ? (
        <p>Finalize a roster first.</p>
      ) : (
        <>
          {clan && (
            <>
              <p className="small">
                Finalized version {data?.version} · {clan.pages} image
                {clan.pages === 1 ? "" : "s"}. Draft changes are not included.
              </p>
              <RosterImageCarousel
                clans={data!.clans}
                selected={tag}
                version={data!.version}
                path={path}
                disabled={!canManage || busy || disabled || confirmTest}
                onSelect={(next) => {
                  setTag(next);
                  changed();
                }}
                onReady={setLoaded}
              />
              <ChannelCombobox
                label="Test channel"
                channels={channels}
                value={channel}
                disabled={!canManage || busy || disabled}
                onChange={(value) => {
                  setChannel(value);
                  setNonce("");
                  setUrl("");
                }}
              />
              <TestChannelDefault
                checked={destination.makeDefault}
                disabled={busy || !canManage}
                error={destination.error}
                onChange={destination.setMakeDefault}
                onReload={destination.reload}
              />
              <p className="small">
                Sends only this clan. No pings. Does not mark announcements as
                sent.
              </p>
              <Button
                icon={Send}
                variant="primary"
                disabled={
                  !canManage || busy || disabled || !channel || !loaded || !!url
                }
                onClick={() => setConfirmTest(true)}
              >
                {busy ? "Sending…" : `Send ${clan.name} test`}
              </Button>
              {url && (
                <p role="status">
                  Test sent.{" "}
                  <a href={url} target="_blank" rel="noopener noreferrer">
                    View in Discord ↗
                  </a>
                </p>
              )}
            </>
          )}
          {data && !data.clans.length && (
            <p>No assigned clans in the finalized roster.</p>
          )}
        </>
      )}
      {error && <p role="alert">{error}</p>}
      {confirmTest && clan && (
        <ConfirmDialog
          heading="Send test image"
          text={`Send only ${clan.name} (${clan.pages} image${clan.pages === 1 ? "" : "s"}) to #${channels.find((c) => c.id === channel)?.name || channel}? No pings.`}
          disabled={busy}
          onCancel={() => setConfirmTest(false)}
          onConfirm={() => void send()}
        />
      )}
    </section>
  );
}

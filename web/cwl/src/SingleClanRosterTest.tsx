import ConfirmDialog from "./ConfirmDialog";
import { Button } from "./rosterUi/primitives";
import { RefreshCw, Eye, Send } from "lucide-react";
import { useDashboardPermission } from "./DashboardPermissions";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import ChannelCombobox from "./ChannelCombobox";
import type { AnnouncementChannel } from "./announcements";
import AnnouncementPreviewDialog from "./AnnouncementPreviewDialog";
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
  const [previewOpen, setPreviewOpen] = useState(false);
  const canManage = useDashboardPermission("cwl_send");
  const [data, setData] = useState<Data | null>(null),
    [tag, setTag] = useState(""),
    [channel, setChannel] = useState(""),
    [channels, setChannels] = useState<AnnouncementChannel[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [url, setUrl] = useState(""),
    [expanded, setExpanded] = useState(false),
    [loaded, setLoaded] = useState(false),
    [nonce, setNonce] = useState("");
  const [confirmTest, setConfirmTest] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const path = `/seasons/${encodeURIComponent(seasonId)}/roster-images`;
  useEffect(() => {
    let active = true;
    setData(null);
    setTag("");
    setUrl("");
    setError("");
    setLoaded(false);
    if (!version) return;
    void Promise.all([
      api<Data>(path),
      api<{ channels: AnnouncementChannel[] }>("/announcement-channels"),
    ])
      .then(([result, choices]) => {
        if (active) {
          setData(result);
          setTag(result.clans[0]?.tag || "");
          setChannels(choices.channels);
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [seasonId, version, refresh]);
  const clan = data?.clans.find((c) => c.tag === tag);
  function changed() {
    setLoaded(false);
    setNonce("");
    setUrl("");
    setError("");
  }
  const imageUrl = (page: number) =>
    `/api/cwl${path}/${encodeURIComponent(tag)}.png?version=${data?.version}&page=${page}`;
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
  const pictures = clan ? (
    <RosterPictures
      clan={clan}
      tag={tag}
      version={data?.version}
      imageUrl={imageUrl}
      onLoad={() => setLoaded(true)}
      onError={() => {
        setLoaded(false);
        setError("Image unavailable. Refresh this section.");
      }}
    />
  ) : null;
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
          <label>
            Clan
            <select
              value={tag}
              disabled={!canManage || busy || disabled || !data}
              onChange={(e) => {
                setTag(e.target.value);
                changed();
              }}
            >
              {!data && <option>Loading…</option>}
              {(["main", "lazy"] as const).map((pool) => (
                <optgroup
                  label={pool === "main" ? "Main CWL" : "Lazy CWL"}
                  key={pool}
                >
                  {data?.clans
                    .filter((c) => c.pool === pool)
                    .map((c) => (
                      <option key={c.tag} value={c.tag}>
                        {c.name} · {c.count} players
                      </option>
                    ))}
                </optgroup>
              ))}
            </select>
          </label>
          {clan && (
            <>
              <p className="small">
                Finalized version {data?.version} · {clan.pages} image
                {clan.pages === 1 ? "" : "s"}. Draft changes are not included.
              </p>
              <details onToggle={(e) => setPreviewOpen(e.currentTarget.open)}>
                <summary>Image preview</summary>
                <div className="clan-roster-pictures">
                  {previewOpen && pictures}
                </div>
                <Button icon={Eye} onClick={() => setExpanded(true)}>
                  Expand preview
                </Button>
              </details>
              {expanded && (
                <AnnouncementPreviewDialog
                  title={clan.name}
                  onClose={() => setExpanded(false)}
                >
                  {pictures}
                </AnnouncementPreviewDialog>
              )}
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
                {busy ? "Sending…" : "Send test image"}
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

function RosterPictures({
  clan,
  tag,
  version,
  imageUrl,
  onLoad,
  onError,
}: {
  clan: Clan;
  tag: string;
  version?: number;
  imageUrl: (page: number) => string;
  onLoad: () => void;
  onError: () => void;
}) {
  return (
    <>
      {Array.from({ length: clan.pages }, (_, i) => (
        <div key={`${tag}:${version}:${i}`}>
          <img
            src={imageUrl(i + 1)}
            alt={`${clan.name} finalized roster, page ${i + 1}`}
            className="clan-roster-image"
            onLoad={onLoad}
            onError={onError}
          />
          <a
            className="button"
            href={imageUrl(i + 1)}
            download={`roster-${tag.slice(1)}-${i + 1}.png`}
          >
            Download{clan.pages > 1 ? ` page ${i + 1}` : " image"}
          </a>
        </div>
      ))}
    </>
  );
}

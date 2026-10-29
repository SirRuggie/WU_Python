import { useEffect, useRef, useState } from "react";
import { api, type Pool } from "./api";
import { useDashboardPermission } from "./DashboardPermissions";
import { Button } from "./rosterUi/primitives";
import ChannelCombobox from "./ChannelCombobox";
import type { AnnouncementChannel } from "./announcements";
import ConfirmDialog from "./ConfirmDialog";
import { hiddenPublicationStatus } from "./publicationStatus";
import RosterImagesTestPanel from "./RosterImagesTestPanel";
import SingleClanRosterTest from "./SingleClanRosterTest";
import {
  imageConfirm,
  imageJobs,
  imagePoolStatus,
  runImageJobs,
  type ImageChannel,
  type ImageData,
  type ImageJob,
} from "./rosterImagePosting";
import "./RosterImagePosting.css";

export default function ClanRosterImages({
  seasonId,
  version,
}: {
  seasonId: string;
  version: number | null;
}) {
  const canSend = useDashboardPermission("cwl_send");
  const [data, setData] = useState<ImageData | null>(null),
    [channels, setChannels] = useState<AnnouncementChannel[]>([]);
  const [saved, setSaved] = useState<ImageChannel[]>([]),
    [chosen, setChosen] = useState<Record<Pool, string>>({
      main: "",
      lazy: "",
    });
  const [error, setError] = useState(""),
    [progress, setProgress] = useState(""),
    [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{
    jobs: ImageJob[];
    text: string;
  } | null>(null);
  const [singleTest, setSingleTest] = useState(false);
  const [testAll, setTestAll] = useState(false);
  const testActive = useRef(false);
  const active = useRef(0),
    running = useRef(false),
    permission = useRef(canSend);
  permission.current = canSend;
  async function reload(generation = active.current) {
    const result = await api<ImageData>(
      `/seasons/${seasonId}/roster-image-posts`,
    );
    if (active.current === generation) setData(result);
  }
  useEffect(() => {
    const generation = ++active.current;
    running.current = false;
    setBusy(false);
    setData(null);
    setConfirm(null);
    setTestAll(false);
    setSingleTest(false);
    setError("");
    setProgress("");
    void reload(generation).catch((e) => {
      if (active.current === generation) setError(e.message);
    });
    if (canSend)
      void Promise.all([
        api<{ channels: ImageChannel[] }>("/roster-image-channels"),
        api<{ channels: AnnouncementChannel[] }>("/announcement-channels"),
      ])
        .then(([config, choices]) => {
          if (active.current !== generation) return;
          setSaved(config.channels);
          setChannels(choices.channels);
          setChosen({
            main:
              config.channels.find((c) => c.pool === "main")?.channel_id || "",
            lazy:
              config.channels.find((c) => c.pool === "lazy")?.channel_id || "",
          });
        })
        .catch((e) => {
          if (active.current === generation) setError(e.message);
        });
    return () => {
      active.current++;
    };
  }, [seasonId, version, canSend]);
  async function save(pool: Pool) {
    if (!canSend || running.current) return;
    running.current = true;
    setBusy(true);
    setError("");
    const generation = active.current;
    try {
      const row = await api<ImageChannel>("/roster-image-channels", "PUT", {
        pool,
        channel_id: chosen[pool],
      });
      if (generation === active.current)
        setSaved((old) => [...old.filter((c) => c.pool !== pool), row]);
    } catch (e) {
      if (generation === active.current) setError((e as Error).message);
    } finally {
      if (generation === active.current) {
        running.current = false;
        setBusy(false);
      }
    }
  }
  async function start() {
    if (!permission.current || running.current || !confirm || !data?.published)
      return;
    const jobs = confirm.jobs,
      generation = active.current;
    running.current = true;
    setBusy(true);
    setConfirm(null);
    setError("");
    try {
      await runImageJobs(seasonId, jobs, {
        active: () =>
          generation === active.current &&
          permission.current &&
          (jobs[0]?.operation !== "test" || testActive.current),
        progress: (t) => {
          if (generation === active.current) setProgress(t);
        },
        completed: () => reload(generation),
      });
    } catch (e) {
      if (generation === active.current) {
        setError((e as Error).message);
        await reload(generation).catch(() => {});
      }
    } finally {
      if (generation === active.current) {
        running.current = false;
        setBusy(false);
      }
    }
  }
  function open(jobs: ImageJob[], text: string) {
    if (canSend && !running.current && jobs.length) setConfirm({ jobs, text });
  }
  return (
    <section className="roster-image-posting roster-ui">
      <h2>Clan roster images</h2>
      {error && <p role="alert">{error}</p>}
      {progress && <p role="status">{progress}</p>}
      {!data ? (
        <p>Loading image status…</p>
      ) : !data.published ? (
        <p>
          {data.last_publication?.withdrawn_at
            ? hiddenPublicationStatus({
                ...data.last_publication,
                withdrawn_at: data.last_publication.withdrawn_at || null,
                joining_instructions:
                  data.last_publication.joining_instructions || "",
              })
            : "Publish the roster first"}{" "}
          ·{" "}
          <a href={`/cwl/publish?season=${seasonId}&step=review`}>
            Finalize roster ›
          </a>
        </p>
      ) : (
        <>
          {(["main", "lazy"] as Pool[]).map((pool) => {
            const config = saved.find((c) => c.pool === pool),
              status = imagePoolStatus(data, pool);
            const jobs = imageJobs(
              data,
              pool,
              config?.channel_id || "",
              status.failedOnly,
            );
            const clans = data.clans.filter((c) => c.pool === pool);
            const rows = [
              ...clans,
              ...data.posts
                .filter(
                  (p) =>
                    p.pool === pool && !clans.some((c) => c.tag === p.clan_tag),
                )
                .map((p) => ({
                  tag: p.clan_tag,
                  name: p.clan_tag,
                  pool,
                  pages: 0,
                  count: 0,
                })),
            ];
            return (
              <section className="image-pool" key={pool}>
                <h3>{pool === "main" ? "Main CWL" : "Lazy CWL"}</h3>
                {canSend && (
                  <>
                    <ChannelCombobox
                      label="Image channel"
                      channels={channels}
                      value={chosen[pool]}
                      disabled={busy}
                      onChange={(value) =>
                        setChosen((old) => ({ ...old, [pool]: value }))
                      }
                    />
                    <Button
                      disabled={
                        busy ||
                        !chosen[pool] ||
                        chosen[pool] === config?.channel_id
                      }
                      onClick={() => void save(pool)}
                    >
                      Save channel
                    </Button>
                    <p className="image-muted">
                      {config
                        ? `#${config.channel_name} · used every season until changed`
                        : "Choose a channel before posting."}
                    </p>
                  </>
                )}
                <p role="status">{status.label}</p>
                {canSend && status.action && (
                  <Button
                    variant="primary"
                    disabled={
                      busy || !jobs.length || jobs.some((j) => !j.channel)
                    }
                    onClick={() =>
                      open(jobs, imageConfirm(jobs, config?.channel_name || ""))
                    }
                  >
                    {status.action}
                  </Button>
                )}
                <details>
                  <summary>Clans · {rows.length}</summary>
                  <ul className="image-clan-list">
                    {rows.map((clan) => {
                      const post = data.posts.find(
                        (p) => p.pool === pool && p.clan_tag === clan.tag,
                      );
                      const uncertain = post?.status === "uncertain";
                      const recoveryOperation =
                        post?.operation === "drop" && clan.pages > 0
                          ? "update"
                          : post?.operation;
                      return (
                        <li key={clan.tag}>
                          <strong>{clan.name}</strong>
                          <span>{post?.status || "Not posted"}</span>
                          {post?.error && <p>{post.error}</p>}
                          {post?.message_id && (
                            <a
                              target="_blank"
                              rel="noopener noreferrer"
                              href={`https://discord.com/channels/644963518025826315/${post.channel_id}/${post.message_id}`}
                            >
                              View in Discord ↗
                            </a>
                          )}
                          {canSend &&
                            post?.status === "failed" &&
                            post.error === "Message was deleted in Discord" &&
                            clan.pages > 0 && (
                              <Button
                                disabled={busy || !config?.channel_id}
                                onClick={() =>
                                  open(
                                    [
                                      {
                                        clan,
                                        operation: "post",
                                        channel: config!.channel_id,
                                        version: data.published!.version,
                                      },
                                    ],
                                    imageConfirm(
                                      [
                                        {
                                          clan,
                                          operation: "post",
                                          channel: config!.channel_id,
                                          version: data.published!.version,
                                        },
                                      ],
                                      config!.channel_name,
                                    ),
                                  )
                                }
                              >
                                Post again
                              </Button>
                            )}
                          {canSend && uncertain && (
                            <Button
                              disabled={busy}
                              onClick={() =>
                                open(
                                  [
                                    {
                                      clan,
                                      operation: recoveryOperation!,
                                      channel:
                                        post.operation === "post"
                                          ? config?.channel_id || ""
                                          : post.channel_id,
                                      version: data.published!.version,
                                    },
                                  ],
                                  post.operation === "post"
                                    ? "This can create a duplicate message if the first one did post."
                                    : `Retry the edit on the same message with version ${data.published!.version}? This won't create a new message.`,
                                )
                              }
                            >
                              {post.operation === "post"
                                ? `Post again anyway · version ${data.published!.version}`
                                : `Retry the edit with version ${data.published!.version}`}
                            </Button>
                          )}
                          {canSend && clan.pages > 0 && (
                            <ImagePreview
                              season={seasonId}
                              version={data.published!.version}
                              clan={clan}
                            />
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </details>
              </section>
            );
          })}
          {canSend && (
            <Button
              disabled={busy}
              onClick={() => {
                testActive.current = true;
                setTestAll(true);
              }}
            >
              Test all…
            </Button>
          )}
          {canSend && testAll && (
            <RosterImagesTestPanel
              data={data}
              channels={channels}
              busy={busy}
              progress={progress}
              error={error}
              onClose={() => {
                testActive.current = false;
                setTestAll(false);
                setConfirm(null);
                void reload().catch((e) => setError(e.message));
              }}
              onConfirm={open}
            />
          )}
          {canSend && (
            <details onToggle={(e) => setSingleTest(e.currentTarget.open)}>
              <summary>Single-clan test</summary>
              {singleTest && (
                <SingleClanRosterTest
                  seasonId={seasonId}
                  version={data.published.version}
                  disabled={busy}
                  acquire={() => {
                    if (running.current) return null;
                    const generation = active.current;
                    running.current = true;
                    setBusy(true);
                    return () => {
                      if (generation !== active.current) return;
                      running.current = false;
                      setBusy(false);
                    };
                  }}
                />
              )}
            </details>
          )}
        </>
      )}
      {confirm && (
        <ConfirmDialog
          heading="Post roster images"
          text={confirm.text}
          confirmLabel="Confirm"
          disabled={busy}
          onCancel={() => setConfirm(null)}
          onConfirm={() => void start()}
        >
          <ul>
            {confirm.jobs.map((j) => (
              <li key={`${j.clan.pool}:${j.clan.tag}`}>
                {j.clan.name} · #
                {channels.find((c) => c.id === j.channel)?.name || j.channel}
              </li>
            ))}
          </ul>
        </ConfirmDialog>
      )}
    </section>
  );
}
function ImagePages({
  season,
  version,
  clan,
}: {
  season: string;
  version: number;
  clan: { name: string; tag: string; pages: number };
}) {
  return (
    <>
      {Array.from({ length: clan.pages }, (_, i) => {
        const src = `/api/cwl/seasons/${season}/roster-images/${encodeURIComponent(clan.tag)}.png?version=${version}&page=${i + 1}`;
        return (
          <div key={i}>
            <img
              loading="lazy"
              src={src}
              alt={`${clan.name} roster page ${i + 1}`}
            />
            <a href={src} download>
              Download page {i + 1}
            </a>
          </div>
        );
      })}
    </>
  );
}

function ImagePreview(props: Parameters<typeof ImagePages>[0]) {
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>Preview + Download</summary>
      {open && <ImagePages {...props} />}
    </details>
  );
}

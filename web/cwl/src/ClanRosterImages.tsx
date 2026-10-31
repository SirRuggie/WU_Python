import { DISCORD_GUILD_ID } from "./discordGuild";
import { useEffect, useRef, useState } from "react";
import { api, type Pool } from "./api";
import { useDashboardPermission } from "./DashboardPermissions";
import { Button } from "./rosterUi/primitives";
import type { AnnouncementChannel } from "./announcements";
import ConfirmDialog from "./ConfirmDialog";
import { hiddenPublicationStatus } from "./publicationStatus";
import RosterImagesTestPanel from "./RosterImagesTestPanel";
import SingleClanRosterTest from "./SingleClanRosterTest";
import {
  imageConfirm,
  imageJobs,
  imagePoolStatus,
  imageRowStatus,
  runImageJobs,
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
  const [error, setError] = useState(""),
    [progress, setProgress] = useState(""),
    [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<{
    jobs: ImageJob[];
    text: string;
    beforeSend?: () => Promise<void>;
  } | null>(null);
  const [result, setResult] = useState<{
    status: "posting" | "complete" | "stopped";
    count: number;
    total: number;
    url: string | null;
    test: boolean;
    channel: string;
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
    setResult(null);
    setTestAll(false);
    setSingleTest(false);
    setError("");
    setProgress("");
    void reload(generation).catch((e) => {
      if (active.current === generation) setError(e.message);
    });
    if (canSend)
      void api<{ channels: AnnouncementChannel[] }>("/announcement-channels")
        .then((choices) => {
          if (active.current !== generation) return;
          setChannels(choices.channels);
        })
        .catch((e) => {
          if (active.current === generation) setError(e.message);
        });
    return () => {
      active.current++;
    };
  }, [seasonId, version, canSend]);
  async function start() {
    if (!permission.current || running.current || !confirm || !data?.published)
      return;
    const beforeSend = confirm.beforeSend;
    const jobs = confirm.jobs,
      generation = active.current;
    running.current = true;
    setBusy(true);
    setConfirm(null);
    setError("");
    setResult({
      status: "posting",
      count: 0,
      total: jobs.length,
      url: null,
      test: jobs[0]?.operation === "test",
      channel:
        channels.find((c) => c.id === jobs[0]?.channel)?.name ||
        jobs[0]?.channel ||
        "the reviewed channels",
    });
    try {
      await beforeSend?.();
      if (generation !== active.current || !permission.current) return;
      await runImageJobs(seasonId, jobs, {
        active: () =>
          generation === active.current &&
          permission.current &&
          (jobs[0]?.operation !== "test" || testActive.current),
        progress: (t) => {
          if (generation === active.current) setProgress(t);
        },
        completed: () => reload(generation),
        delivered: (url) =>
          setResult((previous) =>
            previous
              ? {
                  ...previous,
                  count: previous.count + 1,
                  url: previous.url || url,
                }
              : null,
          ),
      });
      if (jobs[0]?.operation !== "test") {
        for (const pool of new Set(jobs.map((job) => job.clan.pool))) {
          if (generation !== active.current || !permission.current) break;
          const closing = data.closings?.[pool];
          if (closing)
            await api(
              `/seasons/${seasonId}/manage-bridge/${pool}/sequence/closing/update`,
              "POST",
              closing,
            );
        }
      }
      if (
        generation === active.current &&
        permission.current &&
        (jobs[0]?.operation !== "test" || testActive.current)
      )
        setResult((previous) =>
          previous ? { ...previous, status: "complete" } : null,
        );
    } catch (e) {
      if (generation === active.current) {
        setResult((previous) =>
          previous ? { ...previous, status: "stopped" } : null,
        );
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
  function open(
    jobs: ImageJob[],
    text: string,
    beforeSend?: () => Promise<void>,
  ) {
    if (canSend && !running.current && jobs.length)
      setConfirm({
        jobs,
        beforeSend,
        text:
          jobs[0]?.operation === "test"
            ? text
            : text +
              " The closing note will also be checked; if Discord confirms it was deleted, it will be reposted without pings.",
      });
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
            const destination = data.destinations?.[pool];
            const config = destination?.channel_id
              ? {
                  channel_id: destination.channel_id,
                  channel_name:
                    channels.find(
                      (channel) => channel.id === destination.channel_id,
                    )?.name || destination.channel_id,
                }
              : undefined;
            const status = imagePoolStatus(data, pool);
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
                  name: p.clan_name || p.clan_tag,
                  pool,
                  pages: 0,
                  count: 0,
                })),
            ];
            return (
              <section className="image-pool" key={pool}>
                <h3>{pool === "main" ? "Main CWL" : "Lazy CWL"}</h3>
                <p className="image-muted">
                  Images follow the roster announcement in its channel. Existing
                  messages stay in their original channels.
                </p>
                {destination?.reason && <p>{destination.reason}</p>}
                {data.posts.some((post) => post.pool === pool) && (
                  <p>New clans are appended after the closing message.</p>
                )}
                <p role="status">{status.label}</p>
                {canSend &&
                  status.action &&
                  !status.action.startsWith("Post ") && (
                    <Button
                      variant="primary"
                      disabled={
                        busy || !jobs.length || jobs.some((j) => !j.channel)
                      }
                      onClick={() =>
                        open(
                          jobs,
                          imageConfirm(jobs, config?.channel_name || ""),
                        )
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
                      const removed = clan.pages === 0;
                      const dismiss =
                        uncertain && post.operation === "post" && removed;
                      const recoveryOperation = dismiss
                        ? "dismiss"
                        : post?.operation === "update" && removed
                          ? "drop"
                          : post?.operation === "drop" && !removed
                            ? "update"
                            : post?.operation;
                      return (
                        <li key={clan.tag}>
                          <strong>{clan.name}</strong>
                          <span>{imageRowStatus(post?.status)}</span>
                          {post?.error && <p>{post.error}</p>}
                          {dismiss && (
                            <p>
                              Check Discord for {clan.name}'s post. It's no
                              longer in the roster.
                            </p>
                          )}
                          {post?.message_id && (
                            <a
                              target="_blank"
                              rel="noopener noreferrer"
                              href={`https://discord.com/channels/${DISCORD_GUILD_ID}/${post.channel_id}/${post.message_id}`}
                            >
                              View in Discord ↗
                            </a>
                          )}
                          {canSend &&
                            post?.status === "failed" &&
                            post.error === "Message was deleted in Discord" &&
                            clan.pages > 0 && (
                              <Button
                                disabled={busy || !post.channel_id}
                                onClick={() =>
                                  open(
                                    [
                                      {
                                        clan,
                                        operation: "post",
                                        channel: post.channel_id,
                                        version: data.published!.version,
                                      },
                                    ],
                                    imageConfirm(
                                      [
                                        {
                                          clan,
                                          operation: "post",
                                          channel: post.channel_id,
                                          version: data.published!.version,
                                        },
                                      ],
                                      config?.channel_name || post.channel_id,
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
                                      channel: post.channel_id,
                                      version: data.published!.version,
                                      confirmDuplicate:
                                        recoveryOperation === "post",
                                    },
                                  ],
                                  dismiss
                                    ? `Mark ${clan.name}'s post as checked? This only clears our warning and won't change anything in Discord.`
                                    : recoveryOperation === "drop" &&
                                        post.operation === "update"
                                      ? `Edit the existing message to say ${clan.name} is no longer hosting? This won't create a new message.`
                                      : post.operation === "post"
                                        ? "This can create a duplicate message if the first one did post."
                                        : `Retry the edit on the same message with version ${data.published!.version}? This won't create a new message.`,
                                )
                              }
                            >
                              {dismiss
                                ? "Mark as checked"
                                : recoveryOperation === "drop" &&
                                    post.operation === "update"
                                  ? `Mark as no longer hosting · version ${data.published!.version}`
                                  : post.operation === "post"
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
              canSend={canSend}
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
      {result && canSend && (
        <ConfirmDialog
          heading={
            result.status === "complete"
              ? "Done"
              : result.status === "stopped"
                ? "Posting stopped"
                : "Posting images"
          }
          text={
            result.status === "complete"
              ? `${result.test ? "TEST posted" : "Images updated"} · ${result.count} clan messages in #${result.channel} · no pings`
              : result.status === "stopped"
                ? `Stopped after ${result.count} of ${result.total} clan messages. ${error}`
                : progress || "Preparing images…"
          }
          confirmLabel="Close"
          hideCancel
          onCancel={() => {
            setResult(null);
          }}
          onConfirm={() => {
            setProgress(
              result.status === "complete"
                ? "Done · image posting complete"
                : "Check image status before continuing.",
            );
            setResult(null);
          }}
        >
          {result.url &&
            /^https:\/\/discord\.com\/channels\/\d+\/\d+\/\d+$/.test(
              result.url,
            ) && (
              <a
                className="announcement-result-link"
                href={result.url}
                target="_blank"
                rel="noreferrer"
              >
                Open in Discord
              </a>
            )}
        </ConfirmDialog>
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

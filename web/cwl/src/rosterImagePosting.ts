import { ApiError, api, type Pool } from "./api";
import { publicationDate } from "./publicationStatus";
export type ImageClan = {
  tag: string;
  name: string;
  pool: Pool;
  count: number;
  pages: number;
};
export type ImagePost = {
  clan_tag: string;
  pool: Pool;
  channel_id: string;
  message_id: string | null;
  status: "sending" | "posted" | "failed" | "uncertain" | "dropped";
  posted_version: number | null;
  target_version?: number;
  posted_at: string | null;
  error?: string;
  operation: "post" | "update" | "drop";
};
export type ImageData = {
  posts: ImagePost[];
  clans: ImageClan[];
  published: { version: number; published_at: string } | null;
  last_publication: {
    version: number;
    published_at: string;
    withdrawn_at?: string | null;
    joining_instructions?: string;
  } | null;
};
export type ImageChannel = {
  pool: Pool;
  channel_id: string;
  channel_name: string;
};
export type ImageJob = {
  clan: ImageClan;
  operation: "post" | "update" | "drop" | "test";
  channel: string;
  version: number;
};
export function imageJobs(
  data: ImageData,
  pool: Pool,
  channel: string,
  failedOnly = false,
): ImageJob[] {
  if (!data.published) return [];
  const version = data.published.version;
  const clans = data.clans.filter((c) => c.pool === pool);
  const jobs: ImageJob[] = [];
  for (const clan of clans) {
    const old = data.posts.find(
      (p) => p.pool === pool && p.clan_tag === clan.tag,
    );
    if (
      old?.status === "uncertain" ||
      (old?.status === "posted" && old.posted_version === version)
    )
      continue;
    if (failedOnly && old?.status !== "failed") continue;
    const operation =
      old?.message_id && old.error !== "Message was deleted in Discord"
        ? "update"
        : "post";
    jobs.push({
      clan,
      operation,
      channel: operation === "update" ? old!.channel_id : channel,
      version,
    });
  }
  for (const old of data.posts.filter(
    (p) => p.pool === pool && !clans.some((c) => c.tag === p.clan_tag),
  )) {
    if (
      !old.message_id ||
      old.status === "dropped" ||
      old.status === "uncertain" ||
      (failedOnly && old.status !== "failed")
    )
      continue;
    jobs.push({
      clan: { tag: old.clan_tag, name: old.clan_tag, pool, count: 0, pages: 0 },
      operation: "drop",
      channel: old.channel_id,
      version,
    });
  }
  return jobs;
}
export function imagePoolStatus(data: ImageData, pool: Pool) {
  const clans = data.clans.filter((c) => c.pool === pool);
  const posts = data.posts.filter((p) => p.pool === pool);
  const failed = posts.filter((p) => p.status === "failed").length;
  if (failed)
    return {
      label: `${failed} failed · Retry failed`,
      action: "Retry failed",
      failedOnly: true,
    };
  if (
    posts.some(
      (p) =>
        p.status === "posted" && p.posted_version !== data.published?.version,
    )
  )
    return {
      label: `Version ${data.published?.version} published · Update posted images`,
      action: "Update posted images",
      failedOnly: false,
    };
  const done = posts.filter(
    (p) =>
      p.status === "posted" &&
      p.posted_version === data.published?.version &&
      clans.some((c) => c.tag === p.clan_tag),
  );
  if (done.length && done.length === clans.length) {
    const date = done
      .map((p) => p.posted_at || "")
      .sort()
      .at(-1)!;
    return {
      label: `Posted ${date ? publicationDate(date.endsWith("Z") ? date : date.replace(" ", "T") + "Z") : ""} for version ${data.published?.version} · ${done.length} clans`,
      action: "",
      failedOnly: false,
    };
  }
  if (done.length)
    return {
      label: `${done.length} of ${clans.length} posted · Resume`,
      action: "Resume",
      failedOnly: false,
    };
  return {
    label: "Not posted yet",
    action: `Post ${pool === "main" ? "Main" : "Lazy"}`,
    failedOnly: false,
  };
}
export function imageConfirm(jobs: ImageJob[], channelName: string) {
  const updates = jobs.filter((j) => j.operation === "update").length,
    drops = jobs.filter((j) => j.operation === "drop").length;
  if (updates || drops)
    return `Update ${updates} posted messages to version ${jobs[0]?.version}, post ${jobs.filter((j) => j.operation === "post").length} new clan, and mark ${drops} clan as no longer hosting?`;
  return `Post ${jobs.length} clans to #${channelName}? No pings.`;
}
export function imageRequestId() {
  return Array.from(crypto.getRandomValues(new Uint8Array(12)), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}
export async function runImageJobs(
  season: string,
  jobs: ImageJob[],
  options: {
    active: () => boolean;
    progress: (text: string) => void;
    completed: () => Promise<void>;
    send?: typeof api;
    wait?: (ms: number) => Promise<void>;
  },
) {
  const send = options.send || api,
    wait =
      options.wait ||
      ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  for (let i = 0; i < jobs.length && options.active(); i++) {
    const job = jobs[i];
    options.progress(`Posting ${i + 1} of ${jobs.length}… ${job.clan.name}`);
    while (options.active()) {
      try {
        const test = job.operation === "test";
        await send(
          `/seasons/${encodeURIComponent(season)}/${test ? "roster-images" : "roster-image-posts"}/${encodeURIComponent(job.clan.tag)}${test ? "/test" : job.operation === "post" ? "" : "/" + job.operation}`,
          "POST",
          test
            ? {
                version: job.version,
                channel_id: job.channel,
                request_id: imageRequestId(),
              }
            : {
                pool: job.clan.pool,
                version: job.version,
                request_id: imageRequestId(),
              },
        );
        if (options.active()) {
          options.progress(
            `Posting ${i + 1} of ${jobs.length}… ✓ ${job.clan.name}`,
          );
          await options.completed();
        }
        break;
      } catch (error) {
        if (
          error instanceof ApiError &&
          error.status === 429 &&
          error.retryAfter !== undefined
        ) {
          options.progress(`Discord rate limit · waiting ${error.retryAfter}s`);
          await wait(error.retryAfter * 1000);
          continue;
        }
        throw new Error(
          `${job.clan.name}: ${error instanceof Error ? error.message : "Could not confirm delivery. Check Discord."}`,
        );
      }
    }
  }
}

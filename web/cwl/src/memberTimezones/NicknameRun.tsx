import { useState } from "react";
import DiscordIdentity from "../DiscordIdentity";
import FilterChips from "../FilterChips";
import { MemberPages } from "./NicknameReview";
import type { Change, Member, Run } from "./types";
const resultKey = (row: Change) =>
  row.status === "done"
    ? "changed"
    : row.status === "failed"
      ? "failed"
      : row.status === "uncertain"
        ? "manual"
        : ["skipped", "stopped"].includes(row.status || "")
          ? "skipped"
          : "remaining";
const labels = {
  changed: "Changed",
  skipped: "Skipped",
  failed: "Failed",
  manual: "Check manually",
  remaining: "Remaining",
};
export default function NicknameRun({
  run,
  members,
  onStop,
  disabled,
}: {
  run: Run;
  members: Member[];
  onStop: () => void;
  disabled: boolean;
}) {
  const [filter, setFilter] = useState<keyof typeof labels>("changed"),
    [page, setPage] = useState(0);
  const rows = run.rows.filter((r) => resultKey(r) === filter),
    current = Math.min(page, Math.max(0, Math.ceil(rows.length / 25) - 1));
  const profile = (id?: string) => members.find((m) => m.discord_id === id);
  return (
    <section aria-label="Standardize run">
      <h2>
        Standardize progress ·{" "}
        {run.state === "done"
          ? "Finished"
          : run.state === "stopped"
            ? "Stopped"
            : run.state === "stopping"
              ? "Stopping"
              : "Working"}
      </h2>
      <p role="status">
        {["done", "stopped"].includes(run.state)
          ? `${run.state === "done" ? "Done" : "Stopped"}. ${run.rows.filter((r) => r.status === "done").length} changed.${run.rows.some((r) => r.status === "failed") ? ` ${run.rows.filter((r) => r.status === "failed").length} failed.` : ""}${run.rows.some((r) => r.status === "uncertain") ? ` ${run.rows.filter((r) => r.status === "uncertain").length} check manually.` : ""}`
          : `Renaming ${run.rows.filter((r) => ["done", "failed", "uncertain", "stopped", "skipped"].includes(r.status || "")).length} of ${run.rows.length}`}
      </p>
      <progress
        aria-label="Rename progress"
        max={Math.max(1, run.rows.length)}
        value={
          run.rows.filter((r) =>
            ["done", "failed", "uncertain", "stopped", "skipped"].includes(
              r.status || "",
            ),
          ).length
        }
      />
      <p>Renames one at a time. You can stop anytime.</p>
      <div>
        <span>Started by</span>
        <DiscordIdentity
          userId={run.started_by}
          displayName={profile(run.started_by)?.name}
          resolvedMember={profile(run.started_by)?.discord_profile || null}
          variant="compact"
          contact={false}
        />
        {run.stopped_by && (
          <>
            <span>Stopped by</span>
            <DiscordIdentity
              userId={run.stopped_by}
              displayName={profile(run.stopped_by)?.name}
              resolvedMember={profile(run.stopped_by)?.discord_profile || null}
              variant="compact"
              contact={false}
            />
          </>
        )}
      </div>
      {["queued", "stopping"].includes(run.state) && (
        <button
          disabled={disabled || run.state === "stopping"}
          onClick={onStop}
        >
          Stop run
        </button>
      )}
      <FilterChips
        label="Run results"
        value={filter}
        options={(Object.keys(labels) as (keyof typeof labels)[])
          .filter(
            (k) =>
              k !== "remaining" || run.rows.some((r) => resultKey(r) === k),
          )
          .map((k) => ({
            value: k,
            label: labels[k],
            count: run.rows.filter((r) => resultKey(r) === k).length,
          }))}
        onChange={(f) => {
          setFilter(f);
          setPage(0);
        }}
      />
      <MemberPages page={current} total={rows.length} onChange={setPage} />
      <ul className="mt-list">
        {rows.slice(current * 25, (current + 1) * 25).map((r) => (
          <li key={r.discord_id}>
            <DiscordIdentity
              userId={r.discord_id}
              displayName={r.name || r.old_nickname}
              resolvedMember={profile(r.discord_id)?.discord_profile || null}
              variant="compact"
              contact={false}
            />
            <p>
              {r.old_nickname || r.name}
              {r.new_nickname && r.new_nickname !== r.old_nickname
                ? ` → ${r.new_nickname}`
                : ""}
            </p>
            {r.message && <small>{r.message}</small>}
          </li>
        ))}
      </ul>
      {!rows.length && <p>No {labels[filter].toLowerCase()} members.</p>}
    </section>
  );
}

import { useEffect, useRef, useState } from "react";
import ActionPanel from "./ActionPanel";
import { api, ApiError, type Pool } from "./api";
import type { AutoPreview, RosterSnapshot } from "./roster";
import {
  planPresentation,
  publishedMoveCount,
  rosterWeightSummary,
} from "./rosterPlanPresentation";
import "./RosterBalance.css";

type Props = {
  roster: RosterSnapshot;
  seasonId: string;
  tags: string[];
  hiddenTags?: string[];
  trigger: HTMLElement | null;
  automatic?: boolean;
  pool?: Pool | "all";
  onClose: () => void;
  onSaved: () => Promise<void>;
  onBusy: (busy: boolean) => void;
  onPermissionError?: (error: ApiError) => void;
};
const reasons: Record<string, string> = {
  locked: "Locked placement",
  kept: "Locked placement",
  missing_weight: "Missing weight",
  source_unavailable: "Weight source unavailable",
  full: "Matching clans are full",
  no_eligible_rule: "No clan matches the pool and weight rules",
};
const averageText = (value: number | null) =>
  value === null ? "Unknown" : value.toLocaleString("en-US");
export default function RosterBalance({
  roster,
  seasonId,
  tags,
  hiddenTags = [],
  trigger,
  automatic = false,
  pool = "all",
  onClose,
  onSaved,
  onBusy,
  onPermissionError,
}: Props) {
  const pending = useRef(false),
    alive = useRef(true);
  const [hosts, setHosts] = useState<string[]>([]),
    [search, setSearch] = useState("");
  const [chosenPool, setChosenPool] = useState<Pool | "">(
    pool === "all" ? "" : pool,
  );
  const [includeLocked, setIncludeLocked] = useState(false),
    [preview, setPreview] = useState<AutoPreview | null>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [published, setPublished] = useState<
    { tag: string; assigned_clan_tag: string | null }[] | null
  >(null);
  const [publicationStatus, setPublicationStatus] = useState<
    "loading" | "none" | "published" | "unavailable"
  >("loading");
  useEffect(() => {
    alive.current = true;
    let active = true;
    api<{ published: unknown }>(
      `/seasons/${encodeURIComponent(seasonId)}/publication`,
    )
      .then(async (result) => {
        if (!active) return;
        if (!result.published) {
          setPublicationStatus("none");
          return;
        }
        const data = await api<{
          publication_available: boolean;
          accounts: { tag: string; assigned_clan_tag: string | null }[];
        }>(
          `/seasons/${encodeURIComponent(seasonId)}/arrival-check?source=published&background=1`,
        );
        if (active) {
          setPublished(data.publication_available ? data.accounts : []);
          setPublicationStatus(
            data.publication_available ? "published" : "unavailable",
          );
        }
      })
      .catch((cause) => {
        if (active) {
          setPublicationStatus("unavailable");
          if (cause instanceof ApiError && [401, 403].includes(cause.status))
            onPermissionError?.(cause);
        }
      });
    return () => {
      active = false;
      alive.current = false;
    };
  }, [seasonId]);
  const candidates = automatic
    ? roster.accounts
        .filter((a) => !a.assigned_clan_tag && a.pool === chosenPool)
        .map((a) => a.tag)
    : tags;
  const pools = new Set(
    roster.accounts
      .filter((a) => candidates.includes(a.tag))
      .map((a) => a.pool),
  );
  const clans = roster.clans.filter(
    (c) =>
      !c.archived &&
      c.pool &&
      (automatic ? c.pool === chosenPool : pools.has(c.pool)),
  );
  const targetTags = automatic
    ? clans
        .filter((c) => c.capacity === 15 || c.capacity === 30)
        .map((c) => c.tag)
    : hosts;
  const allowed = automatic
    ? !!chosenPool && candidates.length > 0 && targetTags.length > 0
    : hosts.length >= 2 && tags.length > 0 && tags.length <= 50;
  const summary = preview
    ? planPresentation(
        roster.accounts,
        roster.clans,
        preview,
        candidates,
        targetTags,
      )
    : null;
  const clanName = (tag: string | null) =>
    roster.clans.find((c) => c.tag === tag)?.name || tag || "Unassigned";
  async function run(apply: boolean) {
    if (pending.current || !allowed) return;
    pending.current = true;
    setBusy(true);
    onBusy(true);
    setError("");
    const body = automatic
      ? { revision: preview?.revision ?? roster.revision, pool: chosenPool }
      : {
          mode: "balance",
          revision: preview?.revision ?? roster.revision,
          tags,
          clan_tags: hosts,
          include_locked: includeLocked,
        };
    try {
      if (apply && preview) {
        await api(
          `/seasons/${encodeURIComponent(seasonId)}/roster/auto-apply`,
          "POST",
          { ...body, placements: preview.placements },
        );
        if (alive.current) {
          await onSaved();
          onClose();
        }
      } else {
        const value = await api<AutoPreview>(
          `/seasons/${encodeURIComponent(seasonId)}/roster/auto-preview`,
          "POST",
          body,
        );
        if (alive.current) setPreview(value);
      }
    } catch (cause) {
      if (alive.current) {
        setError(
          cause instanceof Error
            ? cause.message
            : "Could not prepare placements. Try again.",
        );
        if (cause instanceof ApiError) {
          if (cause.status === 409) setPreview(null);
          if ([401, 403].includes(cause.status)) onPermissionError?.(cause);
        }
      }
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
      onBusy(false);
    }
  }
  return (
    <ActionPanel
      title={automatic ? "Auto-place unassigned" : "Balance across clans"}
      trigger={trigger}
      busy={busy}
      onClose={onClose}
      expandOnSearchFocus
    >
      <div className="roster-balance-panel">
        {error && (
          <p role="alert" className="notice error">
            {error}
          </p>
        )}
        {!preview ? (
          <>
            <p>
              {automatic
                ? "Place unassigned accounts using the current clan rules."
                : `${tags.length} selected · Choose at least 2 hosting clans.`}
            </p>
            {!!hiddenTags.length && (
              <details>
                <summary>
                  {hiddenTags.length} selected accounts hidden by filters
                </summary>
                <ul>
                  {roster.accounts
                    .filter((a) => hiddenTags.includes(a.tag))
                    .map((a) => (
                      <li key={a.tag}>
                        {a.player_name} · {a.tag}
                      </li>
                    ))}
                </ul>
              </details>
            )}
            {automatic && pool === "all" && (
              <fieldset disabled={busy}>
                <legend>Choose a pool</legend>
                <div className="roster-plan-pools">
                  {(["main", "lazy"] as const).map((p) => (
                    <button
                      type="button"
                      aria-pressed={chosenPool === p}
                      key={p}
                      onClick={() => setChosenPool(p)}
                    >
                      {p === "main" ? "Main CWL" : "Lazy CWL"}
                    </button>
                  ))}
                </div>
              </fieldset>
            )}
            {!automatic && (
              <label>
                Find hosting clans
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  disabled={busy}
                  placeholder="Clan name or tag"
                />
              </label>
            )}
            {(!automatic || chosenPool) && (
              <fieldset disabled={busy}>
                <legend>
                  {automatic ? "Eligible hosting clans" : "Hosting clans"}
                </legend>
                {clans
                  .filter((c) =>
                    [c.name, c.tag].some((v) =>
                      v.toLowerCase().includes(search.toLowerCase().trim()),
                    ),
                  )
                  .map((c) => {
                    const stats = rosterWeightSummary(
                        roster.accounts.filter(
                          (a) => a.assigned_clan_tag === c.tag,
                        ),
                      ),
                      configured = c.capacity === 15 || c.capacity === 30;
                    return (
                      <label className="roster-plan-clan" key={c.tag}>
                        {!automatic && (
                          <input
                            type="checkbox"
                            checked={hosts.includes(c.tag)}
                            disabled={!configured}
                            onChange={(e) =>
                              setHosts(
                                e.target.checked
                                  ? [...hosts, c.tag]
                                  : hosts.filter((t) => t !== c.tag),
                              )
                            }
                          />
                        )}
                        <span>
                          <strong>{c.name}</strong>
                          <small>
                            {c.pool === "main" ? "Main CWL" : "Lazy CWL"} ·{" "}
                            {stats.count}/{c.capacity ?? "Unconfigured"} · Avg{" "}
                            {averageText(stats.average)}
                          </small>
                          {stats.weighed < stats.count && (
                            <small>
                              {stats.weighed} of {stats.count} weighed
                            </small>
                          )}
                          {!configured && (
                            <small>Set capacity in Clan settings first.</small>
                          )}
                        </span>
                      </label>
                    );
                  })}
                {!clans.length && <p>No hosting clans match this pool.</p>}
              </fieldset>
            )}
            {!automatic && (
              <label className="roster-plan-lock">
                <input
                  type="checkbox"
                  checked={includeLocked}
                  disabled={busy}
                  onChange={(e) => setIncludeLocked(e.target.checked)}
                />
                Include locked placements
              </label>
            )}
            <small>
              Missing or unavailable weights are skipped. Signups stay
              unchanged.
            </small>
            <button
              className="primary"
              disabled={busy || !allowed}
              onClick={() => void run(false)}
            >
              {busy ? "Preparing…" : "Preview placements"}
            </button>
          </>
        ) : (
          <>
            <p role="status">
              {preview.placements.length} move
              {preview.placements.length === 1 ? "" : "s"} ·{" "}
              {preview.unassigned.length} skipped · {summary?.unchanged.length}{" "}
              unchanged
            </p>
            {publicationStatus === "published" && published && (
              <p className="notice warning">
                Changes draft placements for{" "}
                {publishedMoveCount(preview, published)} players with published
                assignments. Members see no change until you publish.
              </p>
            )}
            {publicationStatus === "loading" && (
              <p role="status">Checking published assignments…</p>
            )}
            {publicationStatus === "unavailable" && (
              <p className="notice warning">
                Published assignments could not be checked. These are draft
                changes; members see no change until you publish.
              </p>
            )}
            <div className="roster-plan-totals">
              {summary?.clans.map(({ clan, before, after }) => (
                <div key={clan.tag}>
                  <strong>{clan.name}</strong>
                  <span>
                    {before.count} → {after.count}/{clan.effective_capacity}{" "}
                    accounts
                  </span>
                  <span>
                    Avg {averageText(before.average)} →{" "}
                    {averageText(after.average)}
                  </span>
                  {after.weighed < after.count && (
                    <small>
                      {after.weighed} of {after.count} weighed
                    </small>
                  )}
                </div>
              ))}
            </div>
            <details open>
              <summary>Moves · {preview.placements.length}</summary>
              <ul>
                {preview.placements.map((p) => {
                  const a = roster.accounts.find((a) => a.tag === p.tag);
                  return (
                    <li key={p.tag}>
                      <strong>{a?.player_name || p.tag}</strong>
                      <span>
                        {clanName(a?.assigned_clan_tag ?? null)} →{" "}
                        {clanName(p.assigned_clan_tag)}
                      </span>
                      {hiddenTags.includes(p.tag) && (
                        <small>Hidden by filters</small>
                      )}
                    </li>
                  );
                })}
              </ul>
            </details>
            <details open={preview.unassigned.length > 0}>
              <summary>Skipped · {preview.unassigned.length}</summary>
              <ul>
                {preview.unassigned.map((p) => (
                  <li key={p.tag}>
                    {roster.accounts.find((a) => a.tag === p.tag)
                      ?.player_name || p.tag}{" "}
                    · {reasons[p.reason] || p.reason}
                    {hiddenTags.includes(p.tag) && " · Hidden by filters"}
                  </li>
                ))}
              </ul>
            </details>
            <details>
              <summary>Unchanged · {summary?.unchanged.length}</summary>
              <ul>
                {summary?.unchanged.map((a) => (
                  <li key={a.tag}>
                    {a.player_name} · {clanName(a.assigned_clan_tag)}
                    {hiddenTags.includes(a.tag) && " · Hidden by filters"}
                  </li>
                ))}
              </ul>
            </details>
            <div className="roster-plan-footer">
              <button disabled={busy} onClick={() => setPreview(null)}>
                Back to clans
              </button>
              <button
                className="primary"
                disabled={
                  busy ||
                  !preview.placements.length ||
                  preview.revision !== roster.revision
                }
                onClick={() => void run(true)}
              >
                {busy ? "Applying…" : "Apply placements"}
              </button>
            </div>
          </>
        )}
      </div>
    </ActionPanel>
  );
}

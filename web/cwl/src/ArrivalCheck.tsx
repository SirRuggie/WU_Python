import FilterChips from "./FilterChips";
import useConfirmDialog from "./useConfirmDialog";
import CwlNextLink from "./CwlNextLink";
import useFillerMarkQueue from "./useFillerMarkQueue";
import { api } from "./api";
import RosterUndoToast from "./RosterUndoToast";
import type { FillerSaveResult } from "./RosterFillerCheckbox";
import { useDashboardPermission } from "./DashboardPermissions";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import useDeclarationData from "./useDeclarationData";
import { declarationSnapshot } from "./declarationData";
import { declarationGroups } from "./declarationGroups";
import DeclarationClan from "./DeclarationClan";
import DeclarationPingPanel, {
  type PingAttention,
} from "./DeclarationPingPanel";
import useDeclarationExtras from "./useDeclarationExtras";
import DeclarationExtras from "./DeclarationExtras";
import useStaffDetailsPage from "./useStaffDetailsPage";
import { useCwlPool } from "./CwlPoolTabs";
import { hiddenPublicationStatus } from "./publicationStatus";
import { comparisonAge } from "./comparisonLocation";
import { Button, Input } from "./rosterUi/primitives";
import "./ArrivalCheck.css";

export default function ArrivalCheck({
  seasonId,
  onFinalize,
  onResults,
  onDirty = () => {},
  onWorking = () => {},
}: {
  seasonId: string;
  onFinalize?: () => void;
  onResults?: () => void;
  onDirty?: (dirty: boolean) => void;
  onWorking?: (working: boolean) => void;
}) {
  const canMarkRosterFiller = useDashboardPermission("cwl_roster");
  const pingDirty = useRef(false);
  const pingWorking = useRef(false);
  const {
    data,
    error,
    refresh,
    records,
    now,
    checkedAt,
    checking,
    refreshResult,
  } = useDeclarationData(seasonId);
  const fillerQueue = useFillerMarkQueue(seasonId);
  const fillerWorking = fillerQueue.working;
  const undoPending = useRef(false);
  const [localMarks, setLocalMarks] = useState<
    Record<string, FillerSaveResult>
  >({});
  const [markUndo, setMarkUndo] = useState<FillerSaveResult | null>(null);
  const [undoBusy, setUndoBusy] = useState(false);
  const [undoError, setUndoError] = useState("");
  const [explicitRefreshing, setExplicitRefreshing] = useState(false);
  const [pool, setPool] = useCwlPool();
  const { confirm, dialog: confirmation } = useConfirmDialog(seasonId);
  const [pingAttention, setPingAttention] = useState<PingAttention | null>(
    null,
  );
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string[]>([]);
  const [activeClan, setActiveClan] = useState("");
  const [onlyExtras, setOnlyExtras] = useState(false);
  const root = useRef<HTMLElement>(null);
  const directTag = useRef(new URLSearchParams(location.search).get("account"));
  const published =
    !!data?.publication.published &&
    data.arrival.source === "published" &&
    data.arrival.publication_available;
  const extras = useDeclarationExtras(
    seasonId,
    data?.arrival.source || "published",
    data?.arrival.source === "published"
      ? data.arrival.version
      : (data?.roster.revision ?? null),
    !!data && published,
  );
  const context = useMemo(
    () =>
      data && published
        ? {
            roster: {
              ...declarationSnapshot(data),
              revision: Math.max(
                data.roster.revision,
                ...Object.values(localMarks).map((m) => m.revision),
              ),
              accounts: declarationSnapshot(data).accounts.map((a) => {
                const mark = localMarks[a.tag];
                return mark && mark.revision > data.roster.revision
                  ? {
                      ...a,
                      roster_filler: mark.roster_filler,
                      roster_filler_revision: mark.mark_revision,
                    }
                  : a;
              }),
            },
            version: data.arrival.version!,
            signupTags: data.roster.accounts.map((a) => a.tag),
          }
        : undefined,
    [data, published, localMarks],
  );
  const groups = useMemo(
    () =>
      data && context
        ? declarationGroups(
            data,
            context.roster,
            records,
            now,
            extras.data?.clans,
          )
        : [],
    [data, context, records, now, extras.data],
  );
  function applySavedMark(saved?: FillerSaveResult) {
    if (!saved?.tag || typeof saved.roster_filler !== "boolean") {
      setMarkUndo(null);
      refresh();
      return;
    }
    fillerQueue.acceptExternal(saved);
    setMarkUndo(saved.undo ? saved : null);
    setUndoError("");
    setLocalMarks((current) => ({ ...current, [saved.tag!]: saved }));
    extras.applyMark?.(saved);
  }
  fillerQueue.syncRevision(
    Math.max(
      data?.roster.revision || 0,
      extras.data?.revision || 0,
      ...Object.values(localMarks).map((mark) => mark.revision),
    ),
  );
  const fillerDisabled =
    !data ||
    !canMarkRosterFiller ||
    !!data.arrival.season_archived ||
    explicitRefreshing ||
    undoBusy ||
    pingWorking.current;
  useLayoutEffect(
    () => fillerQueue.setDisabled(fillerDisabled),
    [fillerQueue, fillerDisabled],
  );
  fillerQueue.configure(
    (saved) => {
      const last = saved[saved.length - 1];
      setMarkUndo(last?.undo ? last : null);
      setUndoError("");
      setLocalMarks((current) => ({
        ...current,
        ...Object.fromEntries(saved.map((mark) => [mark.tag!, mark])),
      }));
      extras.applyMarks?.(saved);
    },
    () => {
      refresh();
      extras.refresh();
    },
  );
  const markRefresh = useRef<{ rosterId: number; extrasId: number } | null>(
    null,
  );
  function refreshMembers() {
    if (fillerQueue.working || explicitRefreshing) return;
    setExplicitRefreshing(true);
    markRefresh.current = { rosterId: refresh(), extrasId: extras.refresh() };
  }
  useEffect(() => {
    const requested = markRefresh.current;
    if (requested) {
      const rosterResult =
        refreshResult?.id === requested.rosterId ? refreshResult : null;
      const extrasResult =
        extras.refreshResult?.id === requested.extrasId
          ? extras.refreshResult
          : null;
      if (
        rosterResult?.status === "failed" ||
        extrasResult?.status === "failed"
      ) {
        // This explicit attempt failed. A later background poll is not a new
        // Refresh and must never silently clear a halted mutation queue.
        markRefresh.current = null;
        setExplicitRefreshing(false);
      } else if (
        rosterResult?.status === "success" &&
        extrasResult?.status === "success" &&
        !checking &&
        !extras.loading
      ) {
        markRefresh.current = null;
        setExplicitRefreshing(false);
        if (data && extras.data && !error && !extras.error)
          fillerQueue.refreshed(
            Math.max(data.roster.revision, extras.data.revision || 0),
          );
      }
    }
    fillerQueue.observeRows([
      ...(extras.data?.clans
        .flatMap((clan) => [
          ...(clan.extras || []),
          ...(clan.fillers || []),
          ...(clan.low_th || []),
          ...(clan.unpublished || []),
        ])
        .map((row) => ({
          tag: row.tag,
          name: row.name,
          value: !!row.roster_filler,
          markRevision: row.roster_filler_revision || 0,
        })) || []),
      ...(data?.roster.accounts.map((row) => ({
        tag: row.tag,
        name: row.player_name,
        value: !!row.roster_filler,
        markRevision: row.roster_filler_revision || 0,
      })) || []),
    ]);
  }, [
    data,
    extras.data,
    checking,
    extras.loading,
    refreshResult,
    extras.refreshResult,
    error,
    extras.error,
    fillerQueue,
    fillerWorking,
  ]);
  useEffect(() => {
    onWorking(fillerWorking || pingWorking.current);
    onDirty(fillerWorking || pingDirty.current);
  }, [fillerWorking, onWorking, onDirty]);
  useEffect(
    () => () => {
      onWorking(false);
      onDirty(false);
    },
    [],
  );
  const markControl =
    data &&
    canMarkRosterFiller &&
    !data.arrival.season_archived &&
    !pingWorking.current
      ? {
          queue: fillerQueue,
          seasonId,
          revision: Math.max(
            data.roster.revision,
            extras.data?.revision || 0,
            ...Object.values(localMarks).map((m) => m.revision),
          ),
          disabled: explicitRefreshing || undoBusy,
          onChanged: applySavedMark,
        }
      : undefined;
  async function undoMark() {
    if (!markUndo?.undo || undoPending.current || fillerQueue.working) return;
    undoPending.current = true;
    fillerQueue.setWriteBusy(true);
    fillerQueue.clearUndo();
    setUndoBusy(true);
    setUndoError("");
    try {
      const restored = await api<FillerSaveResult>(
        `/seasons/${encodeURIComponent(seasonId)}/roster/undo`,
        "POST",
        { revision: fillerQueue.latestRevision, undo_id: markUndo.undo.id },
      );
      setMarkUndo(null);
      applySavedMark(restored);
    } catch (cause) {
      setMarkUndo(null);
      setUndoError(
        cause instanceof Error ? cause.message : "Could not undo filler mark.",
      );
    } finally {
      undoPending.current = false;
      fillerQueue.setWriteBusy(false);
      setUndoBusy(false);
    }
  }
  const poolGroups = groups.filter((g) => g.pool === pool);
  const visible = poolGroups.filter(
    (g) =>
      pool !== "lazy" ||
      !onlyExtras ||
      !!extras.data?.clans.find(
        (c) =>
          c.tag === g.tag &&
          c.status === "current" &&
          (c.count || 0) + (c.unpublished_count || 0) > 0,
      ),
  );
  const needle = search.trim().toLowerCase();
  function openClan(key: string) {
    setActiveClan(key);
    setExpanded((old) =>
      matchMedia("(max-width: 767px)").matches
        ? [key]
        : [...new Set([...old, key])],
    );
    if (matchMedia("(max-width: 767px)").matches)
      requestAnimationFrame(() => {
        const index = visible.findIndex((g) => g.key === key);
        root.current
          ?.querySelectorAll(".declaration-clan-toggle")
          [index]?.scrollIntoView({ block: "start", behavior: "auto" });
      });
  }
  useEffect(() => {
    markRefresh.current = null;
    setExplicitRefreshing(false);
    setLocalMarks({});
    setMarkUndo(null);
    setUndoError("");
    setExpanded([]);
    setSearch("");
    setActiveClan("");
  }, [seasonId]);
  useEffect(() => {
    if (!needle) return;
    const match = visible.find((g) =>
      g.accounts.some((a) =>
        [a.player_name, a.tag, g.name].some((v) =>
          v.toLowerCase().includes(needle),
        ),
      ),
    );
    if (match) openClan(match.key);
  }, [needle, pool]);
  useEffect(() => {
    if (!directTag.current || !context) return;
    const group = groups.find((g) =>
      g.accounts.some((a) => a.tag === directTag.current),
    );
    if (!group) return;
    directTag.current = null;
    setPool(group.pool);
    setActiveClan(group.key);
    setExpanded([group.key]);
  }, [context, groups]);
  const ordered =
    visible.find((g) => g.key === activeClan && expanded.includes(g.key))
      ?.accounts || [];
  useStaffDetailsPage({
    enabled: !!context,
    seasonId,
    viewOnly: "declaration",
    archived: !!data?.arrival.season_archived,
    onFillerChanged: applySavedMark,
    fillerQueue,
    onChanged: refreshMembers,
    publishedSnapshot: context,
    order: ordered.map((a) => a.tag),
  });
  const hosts = groups.filter((g) => g.tag);
  const locationStatus = (group: (typeof groups)[number]) =>
    group.checkingCount > 0
      ? checking || data?.arrival.updating
        ? ("checking" as const)
        : ("unavailable" as const)
      : undefined;
  const unknownHosts = hosts.some((g) => !!locationStatus(g));
  const extraOnlyHosts =
    extras.data?.clans.filter((c) => !groups.some((g) => g.tag === c.tag)) ||
    [];
  const failedExtras =
    (extras.data?.clans.filter((c) => c.status !== "current").length || 0) +
    groups.filter(
      (g) =>
        g.pool === "lazy" &&
        !!g.tag &&
        !!extras.data &&
        !extras.data.clans.some((c) => c.tag === g.tag),
    ).length;
  return (
    <section
      ref={root}
      className="arrival-check roster-ui"
      aria-label="Declaration readiness"
    >
      {confirmation}
      {fillerQueue.notSaved.length > 0 && (
        <section aria-label="Filler marks not saved">
          <p role="alert">
            {fillerQueue.notSaved.length} not saved. Refresh and tick{" "}
            {fillerQueue.notSaved.length === 1 ? "it" : "them"} again.
          </p>
          {fillerQueue.unknownOutcome && (
            <p>The save may have worked. Refresh to see the result.</p>
          )}
          <ul>
            {fillerQueue.notSaved.map((row) => (
              <li key={row.tag}>{row.name}</li>
            ))}
          </ul>
        </section>
      )}
      {error && (
        <p role="alert">
          {error}
          {error === "Could not check locations" && (
            <Button onClick={refresh}>Retry</Button>
          )}
        </p>
      )}
      {!data && !error && <p role="status">Checking published roster…</p>}
      {data && !published && (
        <p>
          {data.publication.last_publication?.withdrawn_at
            ? hiddenPublicationStatus(data.publication.last_publication)
            : null}{" "}
          {onFinalize ? (
            <button type="button" className="text-link" onClick={onFinalize}>
              Finalize roster first ›
            </button>
          ) : (
            <span>No roster is currently published for members.</span>
          )}
        </p>
      )}
      {data && published && context && (
        <>
          <div className="declaration-overview">
            <p className="declaration-summary" role="status">
              <strong>
                {checking || data.arrival.updating ? (
                  <>
                    Checking…{" "}
                    {
                      hosts.filter(
                        (g) => !locationStatus(g) && g.readiness.ready,
                      ).length
                    }{" "}
                    of {hosts.length} clans confirmed ready
                  </>
                ) : unknownHosts ? (
                  <>
                    {
                      hosts.filter(
                        (g) => !locationStatus(g) && g.readiness.ready,
                      ).length
                    }{" "}
                    of {hosts.length} clans confirmed ready · Locations
                    unavailable
                  </>
                ) : (
                  <>
                    {hosts.filter((g) => g.readiness.ready).length} /{" "}
                    {hosts.length} clans ready to declare
                  </>
                )}
              </strong>{" "}
              {!unknownHosts && (
                <>
                  {" "}
                  · {hosts.reduce((n, g) => n + g.late.length, 0)} players not
                  in their clan
                </>
              )}
              {" · "}
              {extras.error
                ? "Could not check clan members"
                : extras.loading || !extras.data
                  ? "Checking clan members…"
                  : `${extras.data.clans.reduce((n, c) => n + (c.count || 0), 0)} ${failedExtras ? "confirmed " : ""}players not on the roster`}
              {!!extras.data?.clans.some(
                (c) => (c.unpublished_count || 0) > 0,
              ) &&
                ` · ${extras.data.clans.reduce((n, c) => n + (c.unpublished_count || 0), 0)} ${failedExtras ? "confirmed " : ""}not published yet`}
              {failedExtras > 0 &&
                ` · ${failedExtras} ${failedExtras === 1 ? "clan" : "clans"} could not be checked`}
              {" · "}
              <span className="declaration-last-checked">
                {checkedAt
                  ? `Last checked ${comparisonAge(checkedAt, now)}`
                  : unknownHosts
                    ? "No completed location checks"
                    : "No location checks yet"}
              </span>
            </p>
            {pool === "lazy" && (
              <label className="declaration-extras-filter">
                <input
                  type="checkbox"
                  checked={onlyExtras}
                  onChange={(e) => setOnlyExtras(e.target.checked)}
                />
                Clans with players who are not on the roster
              </label>
            )}
            {data.arrival.publication_outdated && (
              <p className="declaration-help">
                Checking published version {data.arrival.version} · the draft
                has changes members cannot see yet
              </p>
            )}
            {pingAttention && (
              <p className="declaration-ping-attention" role="status">
                <span>Declaration pings: {pingAttention.message}</span>
                <Button onClick={pingAttention.reveal}>View error ›</Button>
              </p>
            )}
            <div className="declaration-toolbar">
              <FilterChips
                className="declaration-pools filter-chips--flow"
                label="CWL pool"
                options={(["main", "lazy"] as const).map((p) => {
                  return {
                    value: p,
                    label: (
                      <>
                        {p === "main" ? "Main" : "Lazy"}
                        {checking || data.arrival.updating ? (
                          <>
                            {" · "}Checking…{" "}
                            {
                              hosts.filter(
                                (g) =>
                                  g.pool === p &&
                                  !locationStatus(g) &&
                                  g.readiness.ready,
                              ).length
                            }{" "}
                            of {hosts.filter((g) => g.pool === p).length}
                          </>
                        ) : hosts.some(
                            (g) => g.pool === p && !!locationStatus(g),
                          ) ? null : (
                          <>
                            {" · "}
                            {
                              hosts.filter(
                                (g) => g.pool === p && g.readiness.ready,
                              ).length
                            }
                            /{hosts.filter((g) => g.pool === p).length} ready
                          </>
                        )}
                      </>
                    ),
                  };
                })}
                value={pool}
                onChange={async (p) => {
                  if (pingWorking.current) return;
                  if (
                    pingDirty.current &&
                    !(await confirm(
                      "Discard the unsaved ping channel change?",
                      "Discard channel change",
                    ))
                  )
                    return;
                  pingDirty.current = false;
                  onDirty(fillerQueue.working);
                  setPool(p);
                  setActiveClan("");
                }}
                variant="pill"
                role="group"
                revealSelection
              />
              <Input
                label="Find a player or clan"
                type="search"
                placeholder="Player name, tag or clan"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <div className="declaration-refresh">
                <Button
                  aria-busy={
                    explicitRefreshing ||
                    checking ||
                    extras.loading ||
                    undefined
                  }
                  icon={RefreshCw}
                  disabled={explicitRefreshing || fillerWorking}
                  onClick={() => {
                    refreshMembers();
                  }}
                >
                  {explicitRefreshing
                    ? "Refreshing…"
                    : checking || extras.loading
                      ? "Checking…"
                      : "Refresh"}
                </Button>
              </div>
            </div>
          </div>
          {visible.map((group) => (
            <DeclarationClan
              markControl={markControl}
              key={group.key}
              group={group}
              records={records}
              now={now}
              locationStatus={locationStatus(group)}
              suppressUnavailableLabel={
                unknownHosts && !checking && !data.arrival.updating
              }
              search={needle}
              extra={extras.data?.clans.find((c) => c.tag === group.tag)}
              extraLoading={extras.loading}
              extraError={extras.error}
              request={{
                seasonId,
                viewOnly: "declaration",
                publishedSnapshot: context,
                archived: !!data.arrival.season_archived,
                onFillerChanged: applySavedMark,
                fillerQueue,
                onChanged: refreshMembers,
              }}
              open={expanded.includes(group.key)}
              onToggle={() => {
                if (expanded.includes(group.key))
                  setExpanded((old) => old.filter((k) => k !== group.key));
                else openClan(group.key);
              }}
            />
          ))}
          {pool === "lazy" &&
            extraOnlyHosts
              .filter(
                (c) =>
                  !onlyExtras ||
                  (c.count || 0) + (c.unpublished_count || 0) > 0,
              )
              .map((c) => (
                <section className="declaration-extra-only" key={c.tag}>
                  <h3>{c.name}</h3>
                  <p>
                    No assigned accounts in the shown roster. Member flags only;
                    excluded from readiness.
                  </p>
                  <DeclarationExtras
                    markControl={markControl}
                    row={c}
                    loading={extras.loading}
                    error={extras.error}
                    now={now}
                  />
                </section>
              ))}
          {!visible.length && (
            <p>
              {pool === "lazy" && onlyExtras ? (
                <>
                  No checked clans have players who are not on the roster.{" "}
                  {(extras.error ||
                    extras.data?.clans.some((c) => c.status !== "current")) &&
                    "Some checks are unavailable. "}
                  <Button onClick={() => setOnlyExtras(false)}>
                    Clear filter
                  </Button>
                </>
              ) : (
                <>
                  No {pool === "main" ? "Main" : "Lazy"} CWL accounts in this
                  published roster.
                </>
              )}
            </p>
          )}
          {needle &&
            !visible.some((g) =>
              g.accounts.some((a) =>
                [a.player_name, a.tag, g.name].some((s) =>
                  s.toLowerCase().includes(needle),
                ),
              ),
            ) && <p>No matching players or clans.</p>}

          <DeclarationPingPanel
            key={`${seasonId}:${pool}`}
            seasonId={seasonId}
            pool={pool}
            onAttentionChange={setPingAttention}
            missing={poolGroups.reduce((n, g) => n + g.missingCount, 0)}
            locationStatus={
              poolGroups.some((g) => !!locationStatus(g))
                ? checking || data?.arrival.updating
                  ? "checking"
                  : "unavailable"
                : undefined
            }
            onWorking={(working) => {
              pingWorking.current = working;
              onWorking(working || fillerQueue.working);
            }}
            onDirty={(dirty) => {
              pingDirty.current = dirty;
              onDirty(dirty || fillerQueue.working);
            }}
          />
        </>
      )}
      {undoError && <p role="alert">{undoError}</p>}
      {markUndo?.undo && (
        <RosterUndoToast
          disabled={fillerWorking}
          state={
            undoBusy
              ? {
                  status: "pending",
                  label: `${markUndo.undo.label}${markUndo.tag && fillerQueue.row(markUndo.tag)?.name ? ` · ${fillerQueue.row(markUndo.tag)!.name}` : ""}`,
                }
              : {
                  status: "available",
                  label: `${markUndo.undo.label}${markUndo.tag && fillerQueue.row(markUndo.tag)?.name ? ` · ${fillerQueue.row(markUndo.tag)!.name}` : ""}`,
                }
          }
          onUndo={() => void undoMark()}
          onDismiss={() => setMarkUndo(null)}
        />
      )}
      {data && published && (
        <CwlNextLink label="Results" onNext={onResults} disabled={checking} />
      )}
    </section>
  );
}

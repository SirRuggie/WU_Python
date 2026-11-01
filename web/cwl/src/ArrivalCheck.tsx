import { useEffect, useMemo, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import useDeclarationData from "./useDeclarationData";
import { declarationSnapshot } from "./declarationData";
import { declarationGroups } from "./declarationGroups";
import DeclarationClan from "./DeclarationClan";
import DeclarationPingPanel from "./DeclarationPingPanel";
import useStaffDetailsPage from "./useStaffDetailsPage";
import { useCwlPool } from "./CwlPoolTabs";
import { hiddenPublicationStatus } from "./publicationStatus";
import { comparisonAge, comparisonLocation } from "./comparisonLocation";
import { Button, Input } from "./rosterUi/primitives";
import "./ArrivalCheck.css";

export default function ArrivalCheck({
  seasonId,
  onDirty = () => {},
  onWorking = () => {},
}: {
  seasonId: string;
  onDirty?: (dirty: boolean) => void;
  onWorking?: (working: boolean) => void;
}) {
  const pingDirty = useRef(false);
  const pingWorking = useRef(false);
  const { data, error, refresh, records, now, checkedAt, checking } =
    useDeclarationData(seasonId);
  const [pool, setPool] = useCwlPool();
  const [helpOpen, setHelpOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string[]>([]);
  const [activeClan, setActiveClan] = useState("");
  const root = useRef<HTMLElement>(null);
  const directTag = useRef(new URLSearchParams(location.search).get("account"));
  const published =
    !!data?.publication.published &&
    data.arrival.source === "published" &&
    data.arrival.publication_available;
  const context = useMemo(
    () =>
      data && published
        ? {
            roster: declarationSnapshot(data),
            version: data.arrival.version!,
            signupTags: data.roster.accounts.map((a) => a.tag),
          }
        : undefined,
    [data, published],
  );
  const groups = useMemo(
    () =>
      data && context
        ? declarationGroups(data, context.roster, records, now)
        : [],
    [data, context, records, now],
  );
  const visible = groups.filter((g) => g.pool === pool);
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
    publishedSnapshot: context,
    order: ordered.map((a) => a.tag),
  });
  const hosts = groups.filter((g) => g.tag);
  return (
    <section
      ref={root}
      className="arrival-check roster-ui"
      aria-label="Declaration readiness"
    >
      {error && (
        <p role="alert">
          {error}
          {error === "Couldn't check locations" && (
            <Button onClick={refresh}>Retry</Button>
          )}
        </p>
      )}
      {!data && !error && <p role="status">Checking published roster…</p>}
      {data && !published && (
        <p>
          {data.publication.last_publication?.withdrawn_at
            ? hiddenPublicationStatus(data.publication.last_publication)
            : "Publish the roster first"}{" "}
          ·{" "}
          <a href={`/cwl/publish?season=${seasonId}&step=review`}>
            Finalize roster ›
          </a>
        </p>
      )}
      {data && published && context && (
        <>
          <p className="declaration-summary" role="status">
            <strong>
              {hosts.filter((g) => g.readiness.ready).length} / {hosts.length}{" "}
              clans ready to declare
            </strong>{" "}
            · {hosts.reduce((n, g) => n + g.late.length, 0)} players not in
            their clan
            <button
              type="button"
              className="declaration-info"
              aria-label="About readiness"
              aria-expanded={helpOpen}
              onClick={() => setHelpOpen(!helpOpen)}
            >
              ⓘ
            </button>
          </p>
          <div className="declaration-refresh">
            <span>
              {checkedAt
                ? `Last checked ${comparisonAge(checkedAt, now)}`
                : "Checking…"}
            </span>
            <Button icon={RefreshCw} onClick={refresh}>
              {checking ? "Checking…" : "Refresh"}
            </Button>
          </div>
          {helpOpen && (
            <p className="declaration-help">
              Ready = enough players in their clan for its war size, checked in
              the last 5 minutes.
            </p>
          )}
          {data.arrival.publication_outdated && (
            <p className="declaration-help">
              Checking published version {data.arrival.version} · the draft has
              changes members can't see yet
            </p>
          )}
          <div className="declaration-pools" role="group" aria-label="CWL pool">
            {(["main", "lazy"] as const).map((p) => (
              <Button
                key={p}
                aria-pressed={pool === p}
                onClick={() => {
                  if (pingWorking.current) return;
                  if (
                    pingDirty.current &&
                    !window.confirm("Discard the unsaved ping channel change?")
                  )
                    return;
                  pingDirty.current = false;
                  onDirty(false);
                  setPool(p);
                  setActiveClan("");
                }}
              >
                {p === "main" ? "Main" : "Lazy"} ·{" "}
                {hosts.filter((g) => g.pool === p && g.readiness.ready).length}/
                {hosts.filter((g) => g.pool === p).length} ready
              </Button>
            ))}
          </div>
          <DeclarationPingPanel
            key={`${seasonId}:${pool}`}
            seasonId={seasonId}
            pool={pool}
            missing={visible.reduce(
              (count, g) =>
                count +
                (g.tag
                  ? g.accounts.filter(
                      (a) =>
                        comparisonLocation(records[a.tag], g.tag, now, g.name)
                          .state === "missing",
                    ).length
                  : 0),
              0,
            )}
            onWorking={(working) => {
              pingWorking.current = working;
              onWorking(working);
            }}
            onDirty={(dirty) => {
              pingDirty.current = dirty;
              onDirty(dirty);
            }}
          />
          <Input
            label="Find a player or clan"
            type="search"
            placeholder="Player name, tag or clan"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {!visible.length && (
            <p>
              No {pool === "main" ? "Main" : "Lazy"} CWL accounts in this
              published roster.
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
          {visible.map((group) => (
            <DeclarationClan
              key={group.key}
              group={group}
              records={records}
              now={now}
              search={needle}
              request={{
                seasonId,
                viewOnly: "declaration",
                publishedSnapshot: context,
              }}
              open={expanded.includes(group.key)}
              onToggle={() => {
                if (expanded.includes(group.key))
                  setExpanded((old) => old.filter((k) => k !== group.key));
                else openClan(group.key);
              }}
            />
          ))}
        </>
      )}
    </section>
  );
}

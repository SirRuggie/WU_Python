import { useViewState, type ViewMemory } from "./strikeViewMemory";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import type { Candidate, GroupSummary, Result } from "./replacementTypes";

/** Fetch only expanded clans. Each clan owns its cursor and ignores stale reads. */
export default function ReplacementGroup({
  group,
  memory,
  query,
  refresh,
  open,
  disabled,
  targetTag,
  onToggle,
  renderCandidate,
}: {
  group: GroupSummary;
  memory?: ViewMemory;
  query: string;
  refresh: number;
  open: boolean;
  disabled: boolean;
  targetTag: string;
  onToggle: () => void;
  renderCandidate: (row: Candidate) => ReactNode;
}) {
  const [rows, setRows] = useState<Candidate[]>([]),
    [offset, setOffset] = useViewState(memory, `offset:${group.clan_tag}`, 0);
  const [loading, setLoading] = useState(false),
    [error, setError] = useState("");
  const [retry, setRetry] = useState(0),
    [total, setTotal] = useState(group.listed);
  const generation = useRef(0),
    node = useRef<HTMLElement>(null);
  const filtersMounted = useRef(false);
  useEffect(() => {
    if (!filtersMounted.current) {
      filtersMounted.current = true;
      return;
    }
    setOffset(0);
  }, [query, refresh]);
  useEffect(() => {
    const id = ++generation.current;
    if (!open) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    const params = new URLSearchParams(query);
    params.set("clan", group.clan_tag);
    params.set("offset", String(offset));
    params.set("limit", "25");
    void api<Result>(`/strikes/replacements?${params}`)
      .then(async (result) => {
        let next = result.candidates;
        if (targetTag && !next.some((row) => row.player_tag === targetTag)) {
          const targetParams = new URLSearchParams(params);
          targetParams.set("query", targetTag);
          targetParams.set("offset", "0");
          const target = await api<Result>(
            `/strikes/replacements?${targetParams}`,
          );
          next = [
            ...target.candidates.filter((row) => row.player_tag === targetTag),
            ...next,
          ];
        }
        if (id === generation.current) {
          setRows(next);
          setTotal(result.total ?? group.listed);
        }
      })
      .catch((cause) => {
        if (id === generation.current) {
          setError(
            cause instanceof Error
              ? cause.message
              : "Could not load this clan.",
          );
          if (cause instanceof ApiError && [401, 403].includes(cause.status))
            setRows([]);
        }
      })
      .finally(() => {
        if (id === generation.current) setLoading(false);
      });
    return () => {
      generation.current++;
    };
  }, [open, query, refresh, offset, retry, group.clan_tag, targetTag]);
  useEffect(() => {
    if (open && !loading && targetTag) {
      node.current
        ?.querySelector(`[data-player-tag="${CSS.escape(targetTag)}"]`)
        ?.scrollIntoView({ block: "center" });
    }
  }, [open, loading, targetTag, rows]);
  return (
    <section className="replacement-group" ref={node}>
      <h2>
        <button
          className="replacement-group-summary"
          aria-expanded={open}
          disabled={disabled}
          onClick={onToggle}
        >
          {open ? "▾" : "▸"} {group.clan_name} · {group.listed} listed ·{" "}
          {group.at_three} at 3+ strikes · {group.chopping_block} Chopping Block
        </button>
      </h2>
      {open && (
        <>
          {loading && <p role="status">Loading clan…</p>}
          {error && (
            <div role="alert">
              {error}
              <button
                disabled={loading || disabled}
                onClick={() => setRetry((n) => n + 1)}
              >
                Reload clan
              </button>
            </div>
          )}
          <div className="replacement-list">
            {rows.map((row) => (
              <div key={row.player_tag} data-player-tag={row.player_tag}>
                {renderCandidate(row)}
              </div>
            ))}
          </div>
          <nav
            aria-label={`${group.clan_name} pages`}
            className="replacement-group-actions"
          >
            <button
              disabled={loading || disabled || offset === 0}
              onClick={() => setOffset(Math.max(0, offset - 25))}
            >
              Previous page
            </button>
            <span>
              {total ? offset + 1 : 0}–{Math.min(offset + 25, total)} of {total}
            </span>
            <button
              disabled={loading || disabled || offset + 25 >= total}
              onClick={() => setOffset(offset + 25)}
            >
              Next page
            </button>
          </nav>
        </>
      )}
    </section>
  );
}

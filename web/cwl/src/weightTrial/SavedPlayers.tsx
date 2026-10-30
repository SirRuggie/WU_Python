import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import WeightRow from "./WeightRow";
import { draftFor, validateDraft, type Draft, type Member } from "./model";
export type SavedPlayer = Member & {
  last_saved_clan_tag: string;
  last_saved_clan_name: string;
  updated_at: string;
  current_clan_name?: string | null;
  current_is_family?: boolean | null;
  current_status?: string;
};
export default function SavedPlayers({
  target,
  onState,
  guard,
  resetToken,
  externalBusy = false,
}: {
  resetToken: number;
  externalBusy?: boolean;
  target?: string;
  onState: (count: number, busy: boolean) => void;
  guard: (action: () => void) => void;
}) {
  const [query, setQuery] = useState(target || "");
  const [rows, setRows] = useState<SavedPlayer[]>([]);
  const [values, setValues] = useState<Record<string, Draft>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [term, setTerm] = useState(target || "");
  const request = useRef(0),
    saving = useRef(false);
  const changed = rows.filter(
    (row) => JSON.stringify(values[row.tag]) !== JSON.stringify(draftFor(row)),
  );
  useEffect(() => {
    setValues(Object.fromEntries(rows.map((row) => [row.tag, draftFor(row)])));
  }, [resetToken]);
  useEffect(() => {
    onState(changed.length, busy);
    return () => onState(0, false);
  }, [changed.length, busy, onState]);
  useEffect(() => {
    if (target) {
      setQuery(target);
      setTerm(target);
      setPage(0);
    }
  }, [target]);
  useEffect(() => {
    const id = ++request.current;
    if (!term) {
      setRows([]);
      setValues({});
      return;
    }
    setLoading(true);
    setTotal(0);
    setError("");
    setRows([]);
    setValues({});
    void api<{ players: SavedPlayer[]; total: number }>(
      `/weight-trial/saved-players?q=${encodeURIComponent(term)}&limit=25&offset=${page * 25}`,
    )
      .then((result) => {
        if (id !== request.current) return;
        setRows(result.players);
        setTotal(result.total);
        setValues(
          Object.fromEntries(
            result.players.map((row) => [row.tag, draftFor(row)]),
          ),
        );
      })
      .catch((cause) => {
        if (id === request.current)
          setError(
            cause instanceof Error ? cause.message : "Search unavailable.",
          );
      })
      .finally(() => {
        if (id === request.current) setLoading(false);
      });
    return () => {
      request.current++;
    };
  }, [term, page]);
  async function save(row: SavedPlayer) {
    if (saving.current || externalBusy) return;
    let body;
    try {
      body = { ...validateDraft(values[row.tag]), revision: row.revision };
    } catch (cause) {
      setError((cause as Error).message);
      return;
    }
    saving.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const id = request.current;
    try {
      const result = await api<{ player: SavedPlayer }>(
        `/weight-trial/saved-players/${encodeURIComponent(row.tag)}`,
        "PUT",
        body,
      );
      if (id !== request.current) return;
      setRows((current) =>
        current.map((item) =>
          item.tag === row.tag ? { ...item, ...result.player } : item,
        ),
      );
      setValues((current) => ({
        ...current,
        [row.tag]: draftFor(result.player),
      }));
      setNotice(`Weight saved for ${row.name}.`);
    } catch (cause) {
      if (id === request.current) {
        setError((cause as Error).message);
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
          setRows([]);
          setValues({});
        }
      }
    } finally {
      saving.current = false;
      setBusy(false);
    }
  }
  return (
    <section className="weight-saved-search" aria-label="Find any player">
      <h2>Find any player</h2>
      <p className="small">
        Search every saved weight, including players who have left.
      </p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!busy && !externalBusy)
            guard(() => {
              setTerm(query.trim());
              setPage(0);
            });
        }}
      >
        <label>
          Name or tag
          <input
            type="search"
            maxLength={80}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <button disabled={externalBusy || busy || loading || !query.trim()}>
          Search saved players
        </button>
      </form>
      {loading && <p role="status">Finding saved players…</p>}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {rows.map((row) => (
        <div key={row.tag} className="weight-saved-player">
          <p>
            Last saved in {row.last_saved_clan_name || row.last_saved_clan_tag}{" "}
            · {new Date(row.updated_at).toLocaleDateString()} ·{" "}
            {row.current_status !== "current"
              ? "Current clan unavailable"
              : row.current_is_family
                ? `now in ${row.current_clan_name}`
                : "now not in a family clan"}
          </p>
          <WeightRow
            row={row}
            draft={values[row.tag] || draftFor(row)}
            busy={busy || externalBusy}
            last
            onChange={(draft) =>
              setValues((current) => ({ ...current, [row.tag]: draft }))
            }
            inputRef={() => () => {}}
            onKey={() => {}}
          />
          <button
            disabled={
              externalBusy ||
              busy ||
              !changed.some((item) => item.tag === row.tag)
            }
            onClick={() => void save(row)}
          >
            Save {row.name}
          </button>
        </div>
      ))}
      {term && !loading && !error && (
        <p>
          {total} saved player{total === 1 ? "" : "s"} found
        </p>
      )}
      {page > 0 && (
        <button
          disabled={externalBusy || busy || loading}
          onClick={() => guard(() => setPage(page - 1))}
        >
          Previous results
        </button>
      )}
      {(page + 1) * 25 < total && (
        <button
          disabled={externalBusy || busy || loading}
          onClick={() => guard(() => setPage(page + 1))}
        >
          More results
        </button>
      )}
    </section>
  );
}

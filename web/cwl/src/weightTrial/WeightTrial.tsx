import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import TownHallIcon from "../TownHallIcon";
import {
  copyRows,
  parseWeight,
  pasteWeights,
  weightText,
  type Roster,
} from "./model";
import "./WeightTrial.css";

type Clan = { tag: string; name: string; type?: string };
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Could not complete this action.";
export default function WeightTrial({
  onDirty,
}: {
  onDirty: (dirty: boolean) => void;
}) {
  const [clans, setClans] = useState<Clan[]>([]);
  const [selected, setSelected] = useState("");
  const [search, setSearch] = useState("");
  const [roster, setRoster] = useState<Roster | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [directoryError, setDirectoryError] = useState("");
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [directoryAttempt, setDirectoryAttempt] = useState(0);
  const request = useRef(0);
  const saving = useRef(false);
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const members = roster?.members || [];
  const changed = members.filter(
    (row) => (values[row.tag] ?? "") !== weightText(row.weight),
  );
  const dirty = changed.length > 0;
  useEffect(() => {
    if (!dirty && !busy) return;
    const protect = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [dirty, busy]);
  useEffect(() => {
    onDirty(dirty || busy);
    return () => onDirty(false);
  }, [dirty, busy, onDirty]);
  useEffect(() => {
    let active = true;
    setDirectoryError("");
    setDirectoryLoading(true);
    void api<{ clans: Clan[] }>("/weight-trial/clans")
      .then((result) => {
        if (active)
          setClans(result.clans.sort((a, b) => a.name.localeCompare(b.name)));
      })
      .catch((cause) => {
        if (active) {
          setClans([]);
          setDirectoryError(message(cause));
        }
      })
      .finally(() => {
        if (active) setDirectoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [directoryAttempt]);
  useEffect(() => {
    const id = ++request.current;
    setRoster(null);
    setValues({});
    setError("");
    setNotice("");
    if (!selected) return;
    setLoading(true);
    void api<Roster>(`/weight-trial/clans/${encodeURIComponent(selected)}`)
      .then((result) => {
        if (id !== request.current) return;
        result.members.sort(
          (a, b) =>
            (b.town_hall || 0) - (a.town_hall || 0) ||
            a.name.localeCompare(b.name) ||
            a.tag.localeCompare(b.tag),
        );
        setRoster(result);
        setValues(
          Object.fromEntries(
            result.members.map((row) => [row.tag, weightText(row.weight)]),
          ),
        );
      })
      .catch((cause) => {
        if (id === request.current) setError(message(cause));
      })
      .finally(() => {
        if (id === request.current) setLoading(false);
      });
    return () => {
      request.current++;
    };
  }, [selected, attempt]);
  const discard = () =>
    !dirty ||
    window.confirm(
      "Discard unsaved weights? Saved weights will stay unchanged.",
    );
  const select = (tag: string) => {
    if (!saving.current && discard()) setSelected(tag);
  };
  const refresh = () => {
    if (!saving.current && discard()) setAttempt((value) => value + 1);
  };
  const save = async () => {
    if (saving.current || !roster || !changed.length) return;
    let changes;
    try {
      changes = changed.map((row) => ({
        tag: row.tag,
        revision: row.revision,
        weight: parseWeight(values[row.tag]),
      }));
    } catch (cause) {
      setError(message(cause));
      return;
    }
    saving.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    const id = request.current;
    try {
      const result = await api<Roster>(
        `/weight-trial/clans/${encodeURIComponent(selected)}`,
        "PUT",
        { changes },
      );
      if (id !== request.current) return;
      result.members.sort(
        (a, b) =>
          (b.town_hall || 0) - (a.town_hall || 0) ||
          a.name.localeCompare(b.name) ||
          a.tag.localeCompare(b.tag),
      );
      setRoster(result);
      setValues(
        Object.fromEntries(
          result.members.map((row) => [row.tag, weightText(row.weight)]),
        ),
      );
      setNotice(
        `${changes.length} weight${changes.length === 1 ? "" : "s"} saved.`,
      );
    } catch (cause) {
      if (id === request.current) {
        setError(message(cause));
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
          setRoster(null);
          setValues({});
          setClans([]);
        }
      }
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  const exportAll = async () => {
    if (saving.current) return;
    saving.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/cwl/weight-trial/export.xlsx", {
        credentials: "same-origin",
      });
      if ([401, 403].includes(response.status)) {
        setRoster(null);
        setValues({});
        setClans([]);
      }
      if (!response.ok)
        throw new Error((await response.json()).error || "Export unavailable.");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "clan-weights-test.xlsx";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(
        "Excel download started. It contains all saved test weights, including departed members.",
      );
    } catch (cause) {
      setError(message(cause));
    } finally {
      saving.current = false;
      setBusy(false);
    }
  };
  const filtered = clans.filter((clan) =>
    `${clan.name} ${clan.tag} ${clan.type || ""}`
      .toLowerCase()
      .includes(search.toLowerCase()),
  );
  return (
    <div className="weight-trial">
      <div className="page-head">
        <div>
          <p className="eyebrow">Clan management · Temporary test</p>
          <h1>Clan weights</h1>
          <p>Current members. One weight per account. Enter 149 for 149k.</p>
        </div>
      </div>
      <p className="weight-trial-note">
        Test data only · These weights do not change live CWL calculations.
      </p>
      {directoryError && (
        <p role="alert" className="notice error">
          {directoryError}
          <button onClick={() => setDirectoryAttempt((value) => value + 1)}>
            Retry clans
          </button>
        </p>
      )}
      <div className="weight-trial-layout">
        <aside className="weight-trial-clans">
          <label>
            Find a clan
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Clan name or tag"
            />
          </label>
          <p className="small">
            {filtered.length} of {clans.length} clans
          </p>
          <div className="weight-trial-clan-list" aria-label="Family clans">
            {filtered.map((clan) => (
              <button
                key={clan.tag}
                aria-pressed={selected === clan.tag}
                disabled={busy}
                onClick={() => select(clan.tag)}
              >
                <strong>{clan.name}</strong>
                <small>{clan.type || clan.tag}</small>
              </button>
            ))}
          </div>
          <label className="weight-trial-mobile-select">
            Clan
            <select
              value={selected}
              disabled={busy}
              onChange={(event) => select(event.target.value)}
            >
              <option value="">Choose a clan</option>
              {clans
                .filter(
                  (clan) => clan.tag === selected || filtered.includes(clan),
                )
                .map((clan) => (
                  <option key={clan.tag} value={clan.tag}>
                    {clan.name}
                  </option>
                ))}
            </select>
          </label>
          {directoryLoading && <p role="status">Loading clans…</p>}
          {!directoryLoading && !directoryError && !clans.length && (
            <p>No family clans configured.</p>
          )}
          {!!clans.length && !filtered.length && (
            <p>No clans match your search.</p>
          )}
        </aside>
        <section className="weight-trial-members" aria-label="Member weights">
          <div className="weight-trial-toolbar">
            <div>
              <h2>{roster?.clan.name || "Choose a clan"}</h2>
              {roster && (
                <small>
                  {members.length} current members · Checked{" "}
                  {new Date(roster.checked_at).toLocaleTimeString()}
                </small>
              )}
            </div>
            <button disabled={!selected || busy || loading} onClick={refresh}>
              Refresh members
            </button>
          </div>
          {error && (
            <p className="notice error" role="alert">
              {error}
            </p>
          )}
          {notice && (
            <p role="status" className="notice">
              {notice}
            </p>
          )}
          {loading && <p role="status">Loading current members…</p>}
          {roster && (
            <>
              <div className="weight-trial-columns">
                <span>Player</span>
                <span>Weight (k)</span>
              </div>
              {members.map((row, index) => {
                const value = values[row.tag] ?? "";
                let invalid = false;
                try {
                  parseWeight(value);
                } catch {
                  invalid = true;
                }
                return (
                  <div
                    className={`weight-trial-row${value !== weightText(row.weight) ? " is-edited" : ""}`}
                    key={row.tag}
                  >
                    <div className="weight-trial-player">
                      <TownHallIcon level={row.town_hall} />
                      <span>
                        <strong title={row.name}>{row.name}</strong>
                        <small>{row.tag}</small>
                      </span>
                    </div>
                    <input
                      ref={(element) => {
                        inputs.current[row.tag] = element;
                      }}
                      type="text"
                      inputMode="numeric"
                      aria-label={`Weight in thousands for ${row.name} ${row.tag}`}
                      aria-invalid={invalid}
                      value={value}
                      placeholder="N/A"
                      maxLength={12}
                      disabled={busy}
                      onFocus={(event) => event.currentTarget.select()}
                      onChange={(event) => {
                        setValues((current) => ({
                          ...current,
                          [row.tag]: event.target.value,
                        }));
                        setNotice("");
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          inputs.current[members[index + 1]?.tag]?.focus();
                        }
                      }}
                      onPaste={(event) => {
                        const text = event.clipboardData.getData("text");
                        if (!text.includes("\n") && !text.includes("\t"))
                          return;
                        event.preventDefault();
                        try {
                          const pasted = pasteWeights(
                            text,
                            members.length - index,
                          );
                          setValues((current) => ({
                            ...current,
                            ...Object.fromEntries(
                              pasted.map((weight, offset) => [
                                members[index + offset].tag,
                                weight,
                              ]),
                            ),
                          }));
                          setNotice(
                            `${pasted.length} weights pasted · Not saved yet.`,
                          );
                        } catch (cause) {
                          setError(message(cause));
                        }
                      }}
                    />
                  </div>
                );
              })}
              {!members.length && <p>This clan has no current members.</p>}
              <div className="weight-trial-save">
                <span>
                  {dirty
                    ? `${changed.length} unsaved weight${changed.length === 1 ? "" : "s"}`
                    : "All changes saved"}
                  <small>Enter or Tab moves to the next row.</small>
                </span>
                <button
                  className="primary"
                  disabled={!dirty || busy || loading}
                  onClick={() => void save()}
                >
                  {busy ? "Please wait…" : "Save weights"}
                </button>
              </div>
            </>
          )}
          <details className="weight-trial-export">
            <summary>Export & copy weights</summary>
            <p>
              Excel includes every saved test weight. “Clan at last save” may
              differ from a player’s current clan. Unsaved edits are excluded.
            </p>
            <button disabled={busy || dirty} onClick={() => void exportAll()}>
              Export all saved weights (.xlsx)
            </button>
            <button
              disabled={busy || dirty || !members.length}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(
                    copyRows(members, values),
                  );
                  setNotice("Current member weights copied for Excel.");
                } catch {
                  setError(
                    "Clipboard unavailable. Use the Excel export instead.",
                  );
                }
              }}
            >
              Copy current clan
            </button>
            <p className="small">
              Blank means Not Available. Saved weights stay with the player tag
              when a member leaves or moves clans. You can paste a single Excel
              weight column into the first matching row.
            </p>
          </details>
        </section>
      </div>
    </div>
  );
}

import { Fragment, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import TownHallIcon from "../TownHallIcon";
import {
  copyTable,
  orderedMembers,
  orderLabel,
  draftFor,
  editDraft,
  validateDraft,
  warLoot,
  pasteColumn,
  type Draft,
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
  const [pickerOpen, setPickerOpen] = useState(false);
  const [roster, setRoster] = useState<Roster | null>(null);
  const [values, setValues] = useState<Record<string, Draft>>({});
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [directoryError, setDirectoryError] = useState("");
  const [directoryLoading, setDirectoryLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [directoryAttempt, setDirectoryAttempt] = useState(0);
  const errorPanel = useRef<HTMLParagraphElement | null>(null);
  useEffect(() => {
    if (error) errorPanel.current?.focus();
  }, [error]);
  const pickerButton = useRef<HTMLButtonElement | null>(null);
  const request = useRef(0);
  const saving = useRef(false);
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const members = orderedMembers(roster);
  const changed = members.filter(
    (row) => JSON.stringify(values[row.tag]) !== JSON.stringify(draftFor(row)),
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
        setRoster(result);
        setValues(
          Object.fromEntries(
            result.members.map((row) => [row.tag, draftFor(row)]),
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
    if (!saving.current && discard()) {
      setSelected(tag);
      setPickerOpen(false);
      setSearch("");
      pickerButton.current?.focus();
    }
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
        ...validateDraft(values[row.tag]),
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
      setRoster({
        ...result,
        war_order: roster.war_order,
        war_source: roster.war_source,
      });
      setValues(
        Object.fromEntries(
          result.members.map((row) => [row.tag, draftFor(row)]),
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
          <p>
            Enter loot or full weight. Changing storages recalculates weight
            from loot.
          </p>
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
        <div className="weight-trial-picker">
          <button
            ref={pickerButton}
            aria-expanded={pickerOpen}
            aria-controls="weight-clan-options"
            disabled={busy}
            onClick={() => setPickerOpen(!pickerOpen)}
          >
            {clans.find((clan) => clan.tag === selected)?.name ||
              "Choose a clan"}{" "}
            ▾
          </button>
          {pickerOpen && (
            <div
              id="weight-clan-options"
              onKeyDown={(event) => {
                if (event.key === "Escape") {
                  setPickerOpen(false);
                  pickerButton.current?.focus();
                }
              }}
            >
              <label>
                Find a clan
                <input
                  autoFocus
                  type="search"
                  placeholder="Type a name or tag"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
              <div className="weight-trial-clan-list" aria-label="Family clans">
                {filtered.map((clan) => (
                  <button
                    key={clan.tag}
                    aria-pressed={selected === clan.tag}
                    disabled={busy}
                    onClick={() => select(clan.tag)}
                  >
                    {clan.name}
                    <small>{clan.type || clan.tag}</small>
                  </button>
                ))}
              </div>
              {!filtered.length && (
                <p>
                  {directoryLoading ? "Loading clans…" : "No matching clans."}
                </p>
              )}
            </div>
          )}
        </div>
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
            <p
              ref={errorPanel}
              tabIndex={-1}
              className="notice error"
              role="alert"
            >
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
              <p className="weight-trial-order" role="status">
                {orderLabel(roster)}
                {roster.war_source?.opponent
                  ? ` · vs ${roster.war_source.opponent}`
                  : ""}
              </p>
              <div className="weight-trial-columns" aria-hidden="true">
                <span>#</span>
                <span>Player</span>
                <span>Storages</span>
                <span>Loot</span>
                <span>Full weight</span>
              </div>
              {members.map((row, index) => {
                const draft = values[row.tag] || draftFor(row);
                let invalid = "";
                try {
                  validateDraft(draft);
                } catch (cause) {
                  invalid = message(cause);
                }
                return (
                  <Fragment key={row.tag}>
                    {roster.war_order &&
                      !roster.war_order[row.tag] &&
                      (index === 0 ||
                        roster.war_order[members[index - 1].tag]) && (
                        <h3 className="weight-trial-outside">
                          Current members outside this war
                        </h3>
                      )}
                    <div
                      className={`weight-trial-row${JSON.stringify(draft) !== JSON.stringify(draftFor(row)) ? " is-edited" : ""}`}
                      key={row.tag}
                    >
                      <strong className="weight-trial-position">
                        {roster.war_order
                          ? (roster.war_order[row.tag] ?? "—")
                          : (row.clan_position ?? "—")}
                      </strong>
                      <div className="weight-trial-player">
                        <TownHallIcon level={row.town_hall} />
                        <span>
                          <strong title={row.name}>{row.name}</strong>
                          <small>{row.tag}</small>
                        </span>
                      </div>
                      {(["storages", "loot", "full"] as const).map((field) => (
                        <label className="weight-trial-field" key={field}>
                          <span>
                            {field === "full"
                              ? "Full weight"
                              : field === "loot"
                                ? "Loot"
                                : "Storages"}
                          </span>
                          <input
                            ref={(element) => {
                              inputs.current[`${row.tag}-${field}`] = element;
                            }}
                            type="text"
                            inputMode="numeric"
                            aria-label={`${field === "full" ? "Full weight" : field} for ${row.name} ${row.tag}`}
                            aria-invalid={!!invalid}
                            aria-describedby={
                              invalid ? `weight-error-${index}` : undefined
                            }
                            value={draft[field]}
                            placeholder={field === "storages" ? "5" : "N/A"}
                            maxLength={12}
                            disabled={busy}
                            onFocus={(event) => event.currentTarget.select()}
                            onChange={(event) => {
                              setValues((current) => ({
                                ...current,
                                [row.tag]: editDraft(
                                  draft,
                                  field,
                                  event.target.value,
                                ),
                              }));
                              setNotice("");
                            }}
                            onPaste={(event) => {
                              const text = event.clipboardData.getData("text");
                              if (!/[\n\t]/.test(text)) return;
                              event.preventDefault();
                              try {
                                const updates = pasteColumn(
                                  members,
                                  values,
                                  index,
                                  field,
                                  text,
                                );
                                setValues((current) => ({
                                  ...current,
                                  ...updates,
                                }));
                                setNotice(
                                  `${Object.keys(updates).length} rows pasted · Not saved yet.`,
                                );
                              } catch (cause) {
                                setError(message(cause));
                              }
                            }}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                inputs.current[
                                  `${members[index + 1]?.tag}-${field}`
                                ]?.focus();
                              }
                            }}
                          />
                        </label>
                      ))}
                      {invalid && (
                        <small
                          className="weight-trial-row-error"
                          id={`weight-error-${index}`}
                        >
                          {invalid}
                        </small>
                      )}
                    </div>
                  </Fragment>
                );
              })}
              {!members.length && <p>This clan has no current members.</p>}
              <div className="weight-trial-save">
                <span>
                  {dirty
                    ? `${changed.length} unsaved weight${changed.length === 1 ? "" : "s"}`
                    : "All changes saved"}
                  <small>Enter moves down. Tab moves across.</small>
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
                    copyTable(members, values),
                  );
                  setNotice("Current member weights copied for Excel.");
                } catch {
                  setError(
                    "Clipboard unavailable. Use the Excel export instead.",
                  );
                }
              }}
            >
              Copy member table
            </button>
            <button
              disabled={busy || dirty || !members.length}
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(
                    warLoot(members, values, roster?.war_order),
                  );
                  setNotice(
                    "Loot copied in war order. Check the same clan and war in the FWA sheet, then paste into F17.",
                  );
                } catch (cause) {
                  setError(message(cause));
                }
              }}
            >
              Copy loot for FWA column F
            </button>
            <p className="small">
              Save first. The FWA copy contains loot only, in war order, without
              a heading. Confirm the same war and storage counts in the sheet
              before pasting into F17. If the sheet uses a separate
              small-storage adjustment, check those rows manually; this editor
              calculates loot × storages only. It does not submit weights.
              Players outside the war are excluded; missing war players or loot
              block copying.
            </p>
          </details>
        </section>
      </div>
    </div>
  );
}

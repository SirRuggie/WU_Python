import { fetchReadWithRetry } from "../readRetry";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import ConfirmDialog from "../ConfirmDialog";
import WeightRow from "./WeightRow";
import SavedPlayers from "./SavedPlayers";
import {
  isMissing,
  gaps,
  copyTable,
  sheetWeightWarning,
  orderedMembers,
  orderLabel,
  draftFor,
  validateDraft,
  warLoot,
  pasteColumn,
  type Draft,
  type Roster,
} from "./model";
import "./WeightTrial.css";

type Clan = {
  tag: string;
  name: string;
  type?: string;
  members_count: number | null;
  weighed_count: number | null;
  missing_count: number | null;
  last_saved_at: string | null;
  status: string;
  membership_checked_at?: string | null;
};
const clanLabel = (clan: Clan) =>
  `${clan.name} · ${clan.weighed_count == null ? (clan.status === "loading" ? "Loading progress…" : "Progress unavailable") : `${clan.weighed_count}/${clan.members_count} weighed`} · ${clan.last_saved_at ? `saved ${new Date(clan.last_saved_at).toLocaleDateString()}` : "not saved yet"}${clan.status === "stale" ? (clan.membership_checked_at ? ` · members checked ${new Date(clan.membership_checked_at).toLocaleString()}` : " · members need checking") : ""}`;
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Could not complete this action.";
export default function WeightTrial({
  onDirty,
  onState,
  targetClan,
  targetPlayer,
  seasonId,
  onRoster,
}: {
  onDirty: (dirty: boolean) => void;
  onState?: (state: { count: number; busy: boolean }) => void;
  targetClan?: string;
  targetPlayer?: string;
  seasonId?: string;
  onRoster?: () => void;
}) {
  const [savedReset, setSavedReset] = useState(0);
  const [showMissingLoot, setShowMissingLoot] = useState(false);
  const [filter, setFilter] = useState<"all" | "missing" | "check">("all");
  const [savedState, setSavedState] = useState({ count: 0, busy: false });
  const savedSummary = useCallback(
    (count: number, busy: boolean) => setSavedState({ count, busy }),
    [],
  );
  const [outside, setOutside] = useState<number | null>(null);
  const [pendingAction, setPendingAction] = useState<null | (() => void)>(null);
  const editFocus = useRef<HTMLElement | null>(null);
  const [clans, setClans] = useState<Clan[]>([]);
  const [selected, setSelected] = useState(targetClan || "");
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
  const dirty = changed.length > 0 || savedState.count > 0;
  const totalChanged = changed.length + savedState.count;
  const anyBusy = busy || savedState.busy;
  const missing = members.filter((row) => isMissing(row, draftFor(row)));
  const emptyMissing = missing.filter(
    (row) => !(values[row.tag] || draftFor(row)).loot.trim(),
  );
  const missingWarLoot = members.filter(
    (row) => roster?.war_order?.[row.tag] && !values[row.tag]?.loot.trim(),
  );
  const checks = members.filter((row) =>
    sheetWeightWarning(row.tag, members, values, roster?.war_order),
  );
  const visible = members.filter((row) =>
    filter === "missing"
      ? missing.includes(row) || (showMissingLoot && !draftFor(row).loot.trim())
      : filter === "check"
        ? checks.includes(row) ||
          (changed.includes(row) &&
            !!sheetWeightWarning(row.tag, members, {}, roster?.war_order))
        : true,
  );
  const placeholders = roster ? gaps(roster) : [];
  const entries = [
    ...visible.map((row) => ({
      tag: row.tag,
      position: roster?.war_order?.[row.tag] ?? 1000,
      row,
    })),
    ...(filter === "all"
      ? placeholders.map((gap) => ({ ...gap, row: null }))
      : []),
  ].sort((a, b) => a.position - b.position);
  const guard = (action: () => void) => {
    if (anyBusy || saving.current) return;
    if (dirty) setPendingAction(() => action);
    else action();
  };
  useEffect(() => {
    if (targetClan) setSelected(targetClan);
  }, [targetClan]);
  useEffect(() => {
    if (targetPlayer && roster) {
      const input = inputs.current[`${targetPlayer}-loot`];
      input?.scrollIntoView?.({ block: "center" });
      input?.focus();
    }
  }, [targetPlayer, roster]);
  useEffect(() => {
    onState?.({ count: totalChanged, busy: anyBusy });
  }, [totalChanged, anyBusy, onState]);
  useEffect(() => {
    if (!dirty && !anyBusy) return;
    const protect = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", protect);
    return () => window.removeEventListener("beforeunload", protect);
  }, [dirty, anyBusy]);
  useEffect(() => {
    onDirty(dirty || anyBusy);
    return () => onDirty(false);
  }, [dirty, anyBusy, onDirty]);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let retries = 0;
    const delays = [1000, 2000, 4000, 8000, 16000, 30000];
    setOutside(null);
    setDirectoryError("");
    setDirectoryLoading(true);
    const poll = async () => {
      let again = false;
      try {
        const result = await api<{
          clans: Clan[];
          outside_fwa_missing_count: number | null;
        }>(
          `/weight-trial/clans${seasonId ? `?season_id=${encodeURIComponent(seasonId)}` : ""}`,
        );
        if (!active) return;
        setClans(result.clans);
        setOutside(result.outside_fwa_missing_count);
        setDirectoryError("");
        again = result.clans.some((clan) => clan.status === "loading");
      } catch (cause) {
        if (!active) return;
        setDirectoryError(message(cause));
        const denied =
          cause instanceof ApiError && [401, 403].includes(cause.status);
        if (denied) {
          setClans([]);
          setOutside(null);
        }
        again = !denied;
      } finally {
        if (active) setDirectoryLoading(false);
      }
      if (!active || !again) return;
      if (retries < delays.length) timer = setTimeout(poll, delays[retries++]);
      else {
        setClans((current) =>
          current.map((clan) =>
            clan.status === "loading"
              ? { ...clan, status: "unavailable" }
              : clan,
          ),
        );
        setDirectoryError(
          "Progress is still unavailable. Open a clan to check its members, or try again.",
        );
      }
    };
    void poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [directoryAttempt, seasonId]);
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
        setDirectoryAttempt((value) => value + 1);
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
  const select = (tag: string) =>
    guard(() => {
      setSelected(tag);
      setPickerOpen(false);
      setSearch("");
      setFilter("all");
      pickerButton.current?.focus();
    });
  const refresh = () => guard(() => setAttempt((value) => value + 1));
  const nextMissing = () => {
    setFilter("missing");
    const current = emptyMissing.findIndex(
      (row) => inputs.current[`${row.tag}-loot`] === editFocus.current,
    );
    const target = emptyMissing[(current + 1) % emptyMissing.length];
    requestAnimationFrame(() => {
      const input = inputs.current[`${target?.tag}-loot`];
      input?.scrollIntoView?.({ block: "center" });
      input?.focus();
    });
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
      setDirectoryAttempt((value) => value + 1);
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
      const response = await fetchReadWithRetry(
        "/api/cwl/weight-trial/export.xlsx",
        {
          credentials: "same-origin",
        },
      );
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
      link.download = "clan-weights.xlsx";
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(
        "Excel download started. It contains all saved weights, including departed members.",
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
    <div
      className="weight-trial"
      onFocusCapture={(event) => {
        if (event.target instanceof HTMLInputElement)
          editFocus.current = event.target;
      }}
    >
      {pendingAction && (
        <ConfirmDialog
          heading="Unsaved changes"
          text={`You have ${totalChanged} unsaved weight${totalChanged === 1 ? "" : "s"}.`}
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          danger
          returnFocus={() => editFocus.current}
          onCancel={() => setPendingAction(null)}
          onConfirm={() => {
            const action = pendingAction;
            setPendingAction(null);
            setValues(
              Object.fromEntries(
                members.map((row) => [row.tag, draftFor(row)]),
              ),
            );
            setSavedReset((value) => value + 1);
            action();
          }}
        />
      )}
      <div className="page-head">
        <div>
          <p className="eyebrow">Clan management</p>
          <h1>Clan weights</h1>
          <p>Type each player's loot. Full weight = loot × storages.</p>
        </div>
      </div>
      <details className="weight-trial-note">
        <summary>How weights are used ›</summary>
        <p>Weights saved here win over manual weights and FWA Stats.</p>
        <p>
          Weights follow each player across clans. Save explicitly; manual
          weights or FWA Stats apply only when no saved clan weight exists.
        </p>
        <p>
          Member counts use the last check. Open a clan and refresh members to
          check again.
        </p>
      </details>
      {!!outside && (
        <p>
          {outside} CWL signups outside FWA clans need a weight ·{" "}
          <a
            href={`/cwl/roster?season=${encodeURIComponent(seasonId || "")}`}
            onClick={(event) => {
              if (onRoster && !event.ctrlKey && !event.metaKey) {
                event.preventDefault();
                onRoster();
              }
            }}
          >
            Build roster ›
          </a>
        </p>
      )}
      <SavedPlayers
        externalBusy={busy}
        resetToken={savedReset}
        target={targetPlayer && !targetClan ? targetPlayer : undefined}
        onState={savedSummary}
        guard={guard}
      />
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
            {(clans.find((clan) => clan.tag === selected)
              ? clanLabel(clans.find((clan) => clan.tag === selected)!)
              : "") || "Choose a clan"}{" "}
            ▾
          </button>
          {(pickerOpen || !selected) && (
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
                    {clanLabel(clan)}
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
              {roster && <h2>{roster.clan.name}</h2>}
              {roster && (
                <small>
                  {members.length} current members · Checked{" "}
                  {new Date(roster.checked_at).toLocaleTimeString()}
                </small>
              )}
              {roster && (
                <p className="small" role="status">
                  {roster.last_saved ? (
                    <>
                      Weights last saved on{" "}
                      <time dateTime={roster.last_saved.at}>
                        {new Date(roster.last_saved.at).toLocaleString()}
                      </time>
                      {" by "}
                      <span
                        title={`Discord ID: ${roster.last_saved.discord_id}`}
                      >
                        {roster.last_saved.name}
                      </span>
                      {roster.last_saved.imported
                        ? " · Spreadsheet import"
                        : ""}
                    </>
                  ) : (
                    "Weights not saved yet"
                  )}
                </p>
              )}
            </div>
            {selected && (
              <button disabled={anyBusy || loading} onClick={refresh}>
                Refresh members
              </button>
            )}
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
            <div className="weight-trial-editor">
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
              <div className="weight-trial-filters">
                <p>
                  {missing.length
                    ? `${missing.length} missing`
                    : "All weighed ✓"}{" "}
                  · {checks.length} to check
                </p>
                {(["all", "missing", "check"] as const).map((option) => (
                  <button
                    key={option}
                    aria-pressed={filter === option}
                    onClick={() => {
                      setFilter(option);
                      setShowMissingLoot(false);
                    }}
                  >
                    {option === "all"
                      ? "All"
                      : option === "missing"
                        ? `Missing (${missing.length})`
                        : `Check (${checks.length})`}
                  </button>
                ))}
                <button disabled={!emptyMissing.length} onClick={nextMissing}>
                  Next missing ›
                </button>
              </div>
              {entries.map((entry) => {
                const row = entry.row;
                if (!row) {
                  const gap = placeholders.find(
                    (item) => item.tag === entry.tag,
                  )!;
                  return (
                    <div className="weight-trial-gap" key={entry.tag}>
                      {gap.position} ·{" "}
                      {gap.name
                        ? `${gap.name} · left the clan`
                        : "Not in clan anymore"}
                    </div>
                  );
                }
                const index = visible.indexOf(row);
                return (
                  <Fragment key={row.tag}>
                    {roster.war_order &&
                      !roster.war_order[row.tag] &&
                      (index === 0 ||
                        roster.war_order[visible[index - 1].tag]) && (
                        <h3 className="weight-trial-outside">
                          Current members outside this war
                        </h3>
                      )}
                    <WeightRow
                      row={row}
                      draft={values[row.tag] || draftFor(row)}
                      position={
                        roster.war_order
                          ? roster.war_order[row.tag]
                          : row.clan_position
                      }
                      warning={sheetWeightWarning(
                        row.tag,
                        members,
                        values,
                        roster.war_order,
                      )}
                      busy={anyBusy}
                      last={index === visible.length - 1}
                      inputRef={(field) => (element) => {
                        inputs.current[`${row.tag}-${field}`] = element;
                      }}
                      onChange={(draft) => {
                        setValues((current) => ({
                          ...current,
                          [row.tag]: draft,
                        }));
                        setNotice("");
                      }}
                      onKey={(event, field) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          inputs.current[
                            `${visible[index + 1]?.tag}-${field}`
                          ]?.focus();
                        }
                      }}
                      onPaste={(event, field) => {
                        const text = event.clipboardData.getData("text");
                        if (!/[\n\t]/.test(text)) return;
                        event.preventDefault();
                        try {
                          const updates = pasteColumn(
                            visible,
                            values,
                            index,
                            field,
                            text,
                          );
                          setValues((current) => ({ ...current, ...updates }));
                          setNotice(
                            `${Object.keys(updates).length} rows pasted · Not saved yet.`,
                          );
                        } catch (cause) {
                          setError(message(cause));
                        }
                      }}
                    />
                  </Fragment>
                );
              })}
              {!members.length && <p>This clan has no current members.</p>}
              <div className="weight-trial-save">
                <span>
                  {dirty
                    ? `${changed.length} unsaved weight${changed.length === 1 ? "" : "s"}`
                    : "All changes saved"}
                  <small className="weight-keyboard-hint">
                    Enter moves down. Tab moves across.
                  </small>
                </span>
                <button
                  className="primary"
                  disabled={!changed.length || anyBusy || loading}
                  onClick={() => void save()}
                >
                  {busy ? "Please wait…" : "Save weights"}
                </button>
              </div>
            </div>
          )}
          <details className="weight-trial-export">
            <summary>Export & copy weights</summary>
            <p>
              Excel includes every saved weight. “Clan at last save” may differ
              from a player’s current clan. Unsaved edits are excluded.
            </p>
            <button
              disabled={anyBusy || dirty}
              onClick={() => void exportAll()}
            >
              Export all saved weights (.xlsx)
            </button>
            <button
              disabled={anyBusy || dirty || !members.length}
              onClick={async () => {
                let text: string;
                try {
                  text = copyTable(members, values);
                } catch (cause) {
                  setError(message(cause));
                  return;
                }
                try {
                  await navigator.clipboard.writeText(text);
                  setNotice("Current member weights copied for Excel.");
                } catch {
                  setError(
                    "Copy blocked by the browser. Select the text and copy it manually.",
                  );
                }
              }}
            >
              Copy member table
            </button>
            <button
              disabled={anyBusy || dirty || !members.length}
              onClick={async () => {
                let text: string;
                try {
                  text = warLoot(members, values, roster?.war_order);
                } catch (cause) {
                  setError(message(cause));
                  return;
                }
                try {
                  await navigator.clipboard.writeText(text);
                  setNotice(
                    "Loot copied in war order. Check the same clan and war in the FWA sheet, then paste into F17.",
                  );
                } catch {
                  setError(
                    "Copy blocked by the browser. Select the text and copy it manually.",
                  );
                }
              }}
            >
              Copy loot for FWA column F
            </button>
            <h3>Before pasting into F17</h3>
            <ul className="weight-export-checklist">
              <li>{dirty ? "✕" : "✓"} Weights saved</li>
              <li>
                {missingWarLoot.length > 0
                  ? "✕ Missing loot"
                  : roster?.war_order
                    ? "✓ War loot available"
                    : "✕ War loot not verified"}
              </li>
              <li>
                {roster?.war_order
                  ? "✓ War lineup available"
                  : "✕ War lineup unknown"}
              </li>
              <li>Check: Same war in the sheet</li>
              <li>Check: Storage counts match</li>
              <li>Check: No small-storage adjustment in the sheet</li>
            </ul>
            {missingWarLoot.length > 0 && (
              <p>
                {missingWarLoot.length} player
                {missingWarLoot.length === 1 ? "" : "s"} missing loot ·{" "}
                <button
                  onClick={() => {
                    setFilter("missing");
                    setShowMissingLoot(true);
                  }}
                >
                  Show
                </button>
                {!missing.length && "Saved Not Available rows have no loot."}
              </p>
            )}
            <p className="small">
              Column F excludes members outside this war. Departed war players
              block copying; match the sheet manually using the full table
              export.
            </p>
          </details>
        </section>
      </div>
    </div>
  );
}

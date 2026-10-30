import useUnsavedWork from "./useUnsavedWork";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import useReplacementRevision from "./useReplacementRevision";
import { strikePermissions } from "./strikePermissions";
import ReplacementDeparture from "./ReplacementDeparture";
import ConfirmDialog from "./ConfirmDialog";
import {
  bulkSaveMessage,
  compactWeight,
  enteredWeight,
  selectableTags,
  toggleRosterTag,
  type RosterAccount,
} from "./replacementView";
import "./ReplacementWorkspace.css";

import type {
  Priority,
  Clan,
  Candidate,
  Result,
  GroupSummary,
} from "./replacementTypes";
import ReplacementGroup from "./ReplacementGroup";
const priorityLabels: Record<Priority, string> = {
  replace_first: "Chopping Block",
  high: "High",
  normal: "Normal",
};
const priorityOf = (item: Candidate): Priority =>
  item.priority || (item.is_filler ? "replace_first" : "normal");
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Could not load replacements. Try again.";
const tagPath = (tag: string) => encodeURIComponent(tag);

export default function ReplacementWorkspace({
  permissions,
  isOwner,
  onDirty,
  onWorking,
  initialClan = "",
  onClanChange,
}: {
  permissions: string[];
  isOwner: boolean;
  onDirty?: (dirty: boolean) => void;
  onWorking?: (busy: boolean) => void;
  initialClan?: string;
  onClanChange?: (clan: string) => void;
}) {
  const canManage = strikePermissions(permissions, isOwner).manage;
  const [items, setItems] = useState<Candidate[]>([]);
  const [top, setTop] = useState<Candidate[]>([]);
  const [summaries, setSummaries] = useState<GroupSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [includeLow, setIncludeLow] = useState(false);
  const [townHall, setTownHall] = useState("");
  const [sort, setSort] = useState("priority");
  const [openClans, setOpenClans] = useState<string[]>(
    initialClan ? [initialClan] : [],
  );
  const [targetTag, setTargetTag] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [selectedCandidate, setSelectedCandidate] = useState<Candidate | null>(
    null,
  );
  const [clans, setClans] = useState<Clan[]>([]);
  const [clan, setClan] = useState(initialClan);
  useEffect(() => {
    setClan(initialClan);
  }, [initialClan]);
  const [search, setSearch] = useState("");
  const [weightDraft, setWeightDraft] = useState("");
  const [weight, setWeight] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    onWorking?.(busy);
    return () => onWorking?.(false);
  }, [busy, onWorking]);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [adding, setAdding] = useState(false);
  const [addMode, setAddMode] = useState<"roster" | "tag">("roster");
  const [newClan, setNewClan] = useState("");
  const [roster, setRoster] = useState<RosterAccount[]>([]);
  const [rosterLoading, setRosterLoading] = useState(false);
  const [rosterError, setRosterError] = useState("");
  const [rosterRetry, setRosterRetry] = useState(0);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [newTag, setNewTag] = useState("");
  const [newPriority, setNewPriority] = useState<Priority>("normal");
  const [newNote, setNewNote] = useState("");
  const [editing, setEditing] = useState("");
  const [editRevision, setEditRevision] = useState(0);
  const newBaseline = useReplacementRevision(
    adding && addMode === "tag" ? newTag : "",
  );
  const [editPriority, setEditPriority] = useState<Priority>("normal");
  const [editNote, setEditNote] = useState("");
  const [pendingLeave, setPendingLeave] = useState<(() => void) | null>(null);
  const [clearing, setClearing] = useState<Candidate | null>(null);
  const mutation = useRef(false);
  const editedItem =
    selectedCandidate?.player_tag === editing ? selectedCandidate : null;
  const dirty = adding
    ? !!(selectedTags.length || newTag || newNote || newPriority !== "normal")
    : !!editedItem &&
      (editPriority !== priorityOf(editedItem) ||
        editNote !== (editedItem.note || ""));
  useUnsavedWork(dirty || busy, onDirty);
  const leaveEditor = (action: () => void) => {
    if (mutation.current) return;
    if (dirty) setPendingLeave(() => action);
    else action();
  };
  const request = useRef(0);
  const rosterRequest = useRef(0);
  useEffect(() => {
    const current = ++rosterRequest.current;
    if (!adding || addMode !== "roster" || !newClan) {
      setRoster([]);
      setSelectedTags([]);
      setRosterError("");
      setRosterLoading(false);
      return;
    }
    setRoster([]);
    setRosterError("");
    setRosterLoading(true);
    void api<{ accounts: RosterAccount[] }>(
      `/strikes/replacement-roster?clan=${encodeURIComponent(newClan)}`,
    )
      .then((result) => {
        if (current === rosterRequest.current) {
          const next = result.accounts || [];
          setRoster(next);
          setSelectedTags((selected) =>
            selected.filter((tag) => selectableTags(next).includes(tag)),
          );
        }
      })
      .catch((err) => {
        if (current === rosterRequest.current) setRosterError(errorText(err));
      })
      .finally(() => {
        if (current === rosterRequest.current) setRosterLoading(false);
      });
    return () => {
      rosterRequest.current++;
    };
  }, [adding, addMode, newClan, rosterRetry]);

  const load = useCallback(async () => {
    const current = ++request.current;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (weight) params.set("weight", weight);
      if (clan) params.set("clan", clan);
      params.set("include_low", String(includeLow));
      if (townHall) params.set("town_hall", townHall);
      params.set("sort", sort);
      if (search.trim()) params.set("query", search.trim());
      params.set("limit", "1");
      const result = await api<Result>(
        `/strikes/replacements${params.toString() ? `?${params}` : ""}`,
      );
      if (current !== request.current) return;
      setItems(result.candidates || []);
      if (!weight) setTop(result.top || []);
      setSummaries(result.groups || []);
      setTotal(result.total ?? result.candidates.length);
      setRefresh((value) => value + 1);
      setClans((existing) => [
        ...new Map(
          [...existing, ...(result.clans || [])].map((item) => [
            item.tag,
            item,
          ]),
        ).values(),
      ]);
    } catch (err) {
      if (current === request.current) {
        setError(errorText(err));
        if (err instanceof ApiError && [401, 403].includes(err.status)) {
          setItems([]);
          setTop([]);
          setSummaries([]);
          setSelectedCandidate(null);
          setEditing("");
          setAdding(false);
          setTotal(0);
        }
      }
    } finally {
      if (current === request.current) setLoading(false);
    }
  }, [weight, clan, includeLow, townHall, sort, search]);
  useEffect(() => {
    void load();
    return () => {
      request.current++;
    };
  }, [load]);

  const save = async <T,>(
    action: () => Promise<T>,
    message: string | ((result: T) => string),
    after: () => void,
  ) => {
    if (mutation.current) return;
    mutation.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await action();
      after();
      await load();
      setNotice(typeof message === "function" ? message(result) : message);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("Changed by someone else · Reload");
        return;
      }
      await load();
      if (adding && addMode === "roster") setRosterRetry((value) => value + 1);
      setError(
        `${errorText(err)} The list has been refreshed; check it before retrying.`,
      );
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  };
  const groupQuery = new URLSearchParams({
    include_low: String(includeLow),
    sort,
    query: search,
  });
  if (townHall) groupQuery.set("town_hall", townHall);
  const renderCandidate = (item: Candidate) => (
    <article className="card replacement-row" key={item.player_tag}>
      <div className="replacement-row-main">
        <div className="replacement-identity">
          <strong>{item.player_name || item.player_tag}</strong>
          <small>
            {item.player_tag}
            {item.clan_is_current === false ? " · Last known clan" : ""}
          </small>
          {item.departed && (
            <ReplacementDeparture
              clan={
                item.last_seen_clan_name ||
                clans.find((known) => known.tag === item.last_seen_clan_tag)
                  ?.name ||
                item.last_seen_clan_tag ||
                item.clan_name ||
                "Unknown clan"
              }
              seenAt={item.last_seen_at}
              currentClan={item.current_clan_name || item.current_clan_tag}
            />
          )}
        </div>
        <span className={`replacement-priority ${priorityOf(item)}`}>
          {priorityLabels[priorityOf(item)]}
        </span>
        <div className="replacement-stats">
          <span>
            {item.active_strikes} active{" "}
            {item.active_strikes === 1 ? "strike" : "strikes"}
          </span>
          <span>
            Weight {item.weight == null ? "—" : compactWeight(item.weight)}
          </span>
          {weight && (
            <span>
              Gap{" "}
              {item.weight_difference == null
                ? "—"
                : compactWeight(item.weight_difference)}
            </span>
          )}
        </div>
        {canManage && (
          <button
            disabled={busy}
            className="replacement-more"
            aria-label={`Edit ${item.player_name || item.player_tag}`}
            aria-expanded={editing === item.player_tag}
            onClick={() =>
              leaveEditor(() => {
                if (editing === item.player_tag) {
                  setEditing("");
                  return;
                }
                setSelectedCandidate(item);
                setEditing(item.player_tag);
                setEditRevision(item.revision);
                setAdding(false);
                setEditPriority(priorityOf(item));
                setEditNote(item.note || "");
              })
            }
          >
            Edit
          </button>
        )}
      </div>
      {item.note && <p className="replacement-note">{item.note}</p>}
      {editing === item.player_tag && canManage && (
        <form
          className="replacement-edit-panel"
          onSubmit={(event) => {
            event.preventDefault();
            void save(
              () =>
                api(
                  `/strikes/replacement-list/${tagPath(item.player_tag)}`,
                  "PUT",
                  {
                    priority: editPriority,
                    revision: editRevision,
                    note: editNote.trim(),
                  },
                ),
              "Priority saved.",
              () => setEditing(""),
            );
          }}
        >
          <label>
            Priority
            <select
              disabled={busy}
              value={editPriority}
              onChange={(event) =>
                setEditPriority(event.target.value as Priority)
              }
            >
              <option value="replace_first">Chopping Block</option>
              <option value="high">High</option>
              <option value="normal">Normal</option>
            </select>
          </label>
          <label>
            Note
            <input
              disabled={busy}
              value={editNote}
              onChange={(event) => setEditNote(event.target.value)}
              maxLength={300}
              placeholder="Optional"
            />
          </label>
          <div className="replacement-edit-actions">
            <button
              type="button"
              disabled={busy}
              onClick={() => leaveEditor(() => setEditing(""))}
            >
              Cancel
            </button>
            <button className="primary" disabled={busy}>
              Save
            </button>
            {item.is_manual && (
              <button
                type="button"
                disabled={busy}
                onClick={() => setClearing(item)}
              >
                Clear priority
              </button>
            )}
          </div>
          {item.is_manual && <small>Strike history stays.</small>}
        </form>
      )}
    </article>
  );

  return (
    <section className="replacement-workspace">
      {pendingLeave && canManage && (
        <ConfirmDialog
          heading="Unsaved changes"
          text="Discard your unsaved replacement changes?"
          confirmLabel="Discard"
          cancelLabel="Keep editing"
          disabled={busy}
          onCancel={() => setPendingLeave(null)}
          onConfirm={() => {
            if (mutation.current) return;
            setPendingLeave(null);
            pendingLeave();
          }}
        />
      )}
      {clearing && canManage && (
        <ConfirmDialog
          heading="Clear priority?"
          text={`Clear ${clearing.player_name || clearing.player_tag}'s replacement priority? Strike history stays.`}
          confirmLabel="Clear"
          cancelLabel="Keep"
          danger
          disabled={busy}
          onCancel={() => setClearing(null)}
          onConfirm={() => {
            if (mutation.current) return;
            const target = clearing.player_tag;
            setClearing(null);
            void save(
              () =>
                api(`/strikes/replacement-list/${tagPath(target)}`, "DELETE", {
                  revision: clearing.revision,
                }),
              "Priority cleared.",
              () => setEditing(""),
            );
          }}
        />
      )}
      <div className="page-head">
        <div>
          <p className="eyebrow">Strikes</p>
          <h1>Replacements</h1>
          <p>
            Choose which accounts to replace first. This list does not remove
            anyone from a clan.
          </p>
        </div>
        {canManage && (
          <button
            className="primary"
            disabled={busy}
            onClick={() =>
              leaveEditor(() => {
                if (!adding) {
                  setNewClan(clan);
                  setAddMode("roster");
                  setSelectedTags([]);
                } else {
                  setSelectedTags([]);
                }
                setNewTag("");
                setNewNote("");
                setNewPriority("normal");
                setNotice("");
                setAdding((value) => !value);
                setEditing("");
              })
            }
          >
            {adding ? "Cancel" : "Add accounts"}
          </button>
        )}
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
          <button
            disabled={busy}
            onClick={async () => {
              if (editing) {
                try {
                  const latest = await api<{ revision: number }>(
                    `/strikes/replacement-list/${tagPath(editing)}`,
                  );
                  setEditRevision(latest.revision);
                  setError("");
                } catch (cause) {
                  setError(errorText(cause));
                }
              } else if (adding && addMode === "tag") {
                await newBaseline.reload();
                setError("");
              } else await load();
            }}
          >
            Reload list
          </button>
        </div>
      )}
      {notice && (
        <div className="notice success" role="status">
          {notice}
        </div>
      )}
      {adding && addMode === "tag" && newBaseline.error && (
        <div role="alert">
          {newBaseline.error}
          <button disabled={busy} onClick={() => void newBaseline.reload()}>
            Reload priority
          </button>
        </div>
      )}
      {adding && canManage && (
        <form
          className="card replacement-editor"
          onSubmit={(event) => {
            event.preventDefault();
            if (addMode === "roster") {
              if (
                !newClan ||
                !selectedTags.length ||
                rosterLoading ||
                rosterError
              )
                return;
              const tags = [...selectedTags];
              void save(
                () =>
                  api<{ added_count: number; skipped_count: number }>(
                    "/strikes/replacement-list/bulk",
                    "POST",
                    {
                      clan_tag: newClan,
                      player_tags: tags,
                      priority: newPriority,
                      note: newNote.trim(),
                    },
                  ),
                bulkSaveMessage,
                () => {
                  setAdding(false);
                  setSelectedTags([]);
                  setNewNote("");
                  setNewPriority("normal");
                },
              );
            } else {
              if (
                !newTag.trim() ||
                newBaseline.revision === null ||
                newBaseline.loading
              )
                return;
              void save(
                () =>
                  api("/strikes/replacement-list", "POST", {
                    player_tag: newBaseline.tag,
                    revision: newBaseline.revision,
                    priority: newPriority,
                    note: newNote.trim(),
                  }),
                "Account added.",
                () => {
                  setAdding(false);
                  setNewTag("");
                  setNewNote("");
                  setNewPriority("normal");
                },
              );
            }
          }}
        >
          <h2>Add accounts</h2>
          <label className="replacement-add-mode">
            Choose from
            <select
              value={addMode}
              disabled={busy}
              onChange={(event) => {
                setAddMode(event.target.value as "roster" | "tag");
                setSelectedTags([]);
              }}
            >
              <option value="roster">Clan roster</option>
              <option value="tag">Player tag</option>
            </select>
          </label>
          {addMode === "roster" ? (
            <>
              <label className="replacement-clan-choice">
                Clan
                <select
                  value={newClan}
                  disabled={busy}
                  onChange={(event) => {
                    setNewClan(event.target.value);
                    setSelectedTags([]);
                  }}
                  required
                >
                  <option value="">Choose clan</option>
                  {clans.map((item) => (
                    <option key={item.tag} value={item.tag}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
              {newClan && (
                <div className="replacement-roster">
                  <div className="replacement-roster-head">
                    <strong>Accounts</strong>
                    {!rosterLoading &&
                      !rosterError &&
                      selectableTags(roster).length > 0 && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() =>
                            setSelectedTags(
                              selectedTags.length ===
                                selectableTags(roster).length
                                ? []
                                : selectableTags(roster),
                            )
                          }
                        >
                          {selectedTags.length === selectableTags(roster).length
                            ? "Clear all"
                            : "Select all"}
                        </button>
                      )}
                  </div>
                  {rosterLoading ? (
                    <p role="status">Loading roster…</p>
                  ) : rosterError ? (
                    <div className="notice error" role="alert">
                      {rosterError}
                      <button
                        type="button"
                        onClick={() => setRosterRetry((value) => value + 1)}
                      >
                        Retry
                      </button>
                    </div>
                  ) : roster.length ? (
                    <div className="replacement-roster-list">
                      {roster.map((account) => (
                        <label
                          key={account.player_tag}
                          className={account.is_manual ? "is-listed" : ""}
                        >
                          <input
                            type="checkbox"
                            checked={
                              account.is_manual ||
                              selectedTags.includes(account.player_tag)
                            }
                            disabled={busy || account.is_manual}
                            onChange={() =>
                              setSelectedTags((current) =>
                                toggleRosterTag(
                                  current,
                                  account.player_tag,
                                  roster,
                                ),
                              )
                            }
                          />
                          <span>
                            <strong>
                              {account.player_name || account.player_tag}
                            </strong>
                            <small>{account.player_tag}</small>
                          </span>
                          {account.is_manual && <small>Listed</small>}
                        </label>
                      ))}
                    </div>
                  ) : (
                    <p>No accounts found in this clan.</p>
                  )}
                </div>
              )}
            </>
          ) : (
            <label className="replacement-tag-choice">
              Player tag
              <input
                value={newTag}
                disabled={busy}
                onChange={(event) => setNewTag(event.target.value)}
                placeholder="#PLAYERTAG"
                required
              />
            </label>
          )}
          <div className="replacement-add-details">
            <label>
              Priority
              <select
                value={newPriority}
                disabled={busy}
                onChange={(event) =>
                  setNewPriority(event.target.value as Priority)
                }
              >
                <option value="replace_first">Chopping Block</option>
                <option value="high">High</option>
                <option value="normal">Normal</option>
              </select>
            </label>
            <label>
              Note (optional)
              <input
                value={newNote}
                disabled={busy}
                onChange={(event) => setNewNote(event.target.value)}
                maxLength={300}
                placeholder="e.g. Temporary filler"
              />
            </label>
          </div>
          <button
            className="primary"
            disabled={
              busy ||
              (addMode === "roster"
                ? !newClan ||
                  !selectedTags.length ||
                  rosterLoading ||
                  !!rosterError
                : !newTag.trim() ||
                  newBaseline.revision === null ||
                  newBaseline.loading)
            }
          >
            {busy
              ? "Saving…"
              : addMode === "roster"
                ? `Add ${selectedTags.length} ${selectedTags.length === 1 ? "account" : "accounts"}`
                : "Add account"}
          </button>
        </form>
      )}
      {!adding && (
        <>
          <section className="replacement-match">
            <h2>
              Got a recruit? Enter their weight
              {weight ? ` · ${compactWeight(enteredWeight(weight))}` : ""}
            </h2>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                const nextWeight = weightDraft.trim();
                if (
                  nextWeight &&
                  clan &&
                  !clans.find((item) => item.tag === clan)?.is_fwa
                )
                  setClan("");
                setWeight(nextWeight);
              }}
            >
              <label>
                Recruit war weight
                <input
                  type="number"
                  min="1"
                  step="1"
                  disabled={busy || !!editing}
                  value={weightDraft}
                  onChange={(event) => setWeightDraft(event.target.value)}
                  placeholder="e.g. 149"
                />
              </label>
              <button disabled={busy || !!editing} type="submit">
                Match
              </button>
              {weight && (
                <button
                  disabled={busy || !!editing}
                  type="button"
                  onClick={() => {
                    setWeight("");
                    setWeightDraft("");
                  }}
                >
                  Clear
                </button>
              )}
            </form>
            <small>
              FWA clans only. Enter 149 or 149000 for a weight of 149,000.
            </small>
          </section>
          <section
            className="replacement-top"
            aria-label="Top 10 across all clans"
          >
            <h2>Top 10 across all clans</h2>
            <ol>
              {top.map((item) => (
                <li key={item.player_tag}>
                  <button
                    disabled={busy || !!editing}
                    onClick={() => {
                      const tag = item.clan_tag || item.last_seen_clan_tag;
                      if (tag) {
                        setOpenClans((current) => [
                          ...new Set([...current, tag]),
                        ]);
                        setTargetTag(item.player_tag);
                      }
                    }}
                  >
                    <strong>{item.player_name}</strong>
                    <span>
                      {item.clan_name || item.last_seen_clan_name} ·{" "}
                      {priorityLabels[priorityOf(item)]} · {item.active_strikes}{" "}
                      active ·{" "}
                      {item.weight == null
                        ? "No weight"
                        : compactWeight(item.weight)}
                    </span>
                  </button>
                </li>
              ))}
            </ol>
          </section>
          <div className="replacement-filters">
            <label>
              <input
                type="checkbox"
                checked={includeLow}
                disabled={busy || !!editing}
                onChange={(event) => setIncludeLow(event.target.checked)}
              />
              Show 1–2 strikes too
            </label>
            <label>
              Town Hall
              <select
                value={townHall}
                disabled={busy || !!editing}
                onChange={(event) => setTownHall(event.target.value)}
              >
                <option value="">All Town Halls</option>
                {Array.from({ length: 18 }, (_, i) => i + 1).map((th) => (
                  <option key={th} value={th}>
                    TH {th}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Sort
              <select
                value={sort}
                disabled={busy || !!editing}
                onChange={(event) => setSort(event.target.value)}
              >
                <option value="priority">Priority</option>
                <option value="strikes">Most strikes</option>
                <option value="weight">Weight</option>
              </select>
            </label>
            <label>
              Find account
              <input
                type="search"
                disabled={busy || !!editing}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Name or player tag"
              />
            </label>
            <label>
              Clan
              <select
                value={clan}
                disabled={busy || !!editing}
                onChange={(event) => {
                  setClan(event.target.value);
                  onClanChange?.(event.target.value);
                }}
              >
                <option value="">All clans</option>
                {clans
                  .filter((item) => !weight || item.is_fwa)
                  .map((item) => (
                    <option key={item.tag} value={item.tag}>
                      {item.name}
                    </option>
                  ))}
              </select>
            </label>
          </div>
          {weight && (
            <p className="replacement-weight-note">
              FWA only · priority, strikes, then weight (
              {compactWeight(enteredWeight(weight))}).
            </p>
          )}
          <div className="replacement-count" role="status">
            {loading
              ? "Loading replacements…"
              : `${total} ${total === 1 ? "account" : "accounts"} · ${includeLow ? "1+ strikes" : "3+ strikes"}`}
          </div>
          {!loading && !error && total === 0 && (
            <div className="card replacement-empty">
              {search ? "No accounts match." : "No replacement accounts yet."}
            </div>
          )}
          {!loading && !weight && (
            <>
              <div className="replacement-group-actions">
                <button
                  disabled={busy || !!editing}
                  onClick={() => setOpenClans(summaries.map((g) => g.clan_tag))}
                >
                  Expand all
                </button>
                <button
                  disabled={busy || !!editing}
                  onClick={() => setOpenClans([])}
                >
                  Collapse all
                </button>
              </div>
              {summaries.map((group) => (
                <ReplacementGroup
                  key={group.clan_tag}
                  group={group}
                  query={groupQuery.toString()}
                  refresh={refresh}
                  targetTag={targetTag}
                  open={openClans.includes(group.clan_tag)}
                  disabled={busy || !!editing}
                  onToggle={() =>
                    leaveEditor(() =>
                      setOpenClans((current) =>
                        current.includes(group.clan_tag)
                          ? current.filter((t) => t !== group.clan_tag)
                          : [...current, group.clan_tag],
                      ),
                    )
                  }
                  renderCandidate={renderCandidate}
                />
              ))}
            </>
          )}
          {!loading && weight && (
            <div className="replacement-list">{items.map(renderCandidate)}</div>
          )}
        </>
      )}
    </section>
  );
}

import { useEffect, useRef, useState } from "react";
import { Plus, RotateCw, Settings2, X } from "lucide-react";
import ActionPanel from "./ActionPanel";
import RosterMenu from "./rosterUi/Menu";
import { Button, Input, StatusPill } from "./rosterUi/primitives";
import { api, type Account, type Pool, type Season } from "./api";
import { useDashboardPermission } from "./DashboardPermissions";
import MemberPicker from "./MemberPicker";
import StaffPlayerButton from "./StaffPlayerButton";
import StaffTagSignup from "./StaffTagSignup";
import TownHallIcon from "./TownHallIcon";
import useUnsavedWork from "./useUnsavedWork";
import "./StaffSignupControls.css";

type Choice = Account & { signed_up_pool: Pool | null };
type Props = {
  season: Season;
  onChanged: (added: boolean) => Promise<void>;
  onDirty: (dirty: boolean) => void;
  onBusy: (busy: boolean) => void;
  onOpenChange?: (open: boolean) => void;
  disabled?: boolean;
};

export default function StaffSignupControls({
  season,
  onChanged,
  onDirty,
  onBusy,
  onOpenChange,
  disabled = false,
}: Props) {
  const canSettings = useDashboardPermission("cwl_settings");
  const [open, setOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uid, setUid] = useState("");
  const [pool, setPool] = useState<Pool | "">("");
  const [accounts, setAccounts] = useState<Choice[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const [mode, setMode] = useState<"tag" | "member">("member");
  const [search, setSearch] = useState("");
  const [tagDirty, setTagDirty] = useState(false);
  const [tagBusy, setTagBusy] = useState(false);
  const [editorDirty, setEditorDirty] = useState(false);
  const [editorBusy, setEditorBusy] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const working = busy || tagBusy || editorBusy;
  const dirty =
    editorDirty ||
    (open && (!!uid || !!pool || selected.length > 0 || tagDirty));
  const archived = season.status === "archived";
  const addButton = useRef<HTMLButtonElement>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);

  useUnsavedWork(dirty || working, onDirty);
  useEffect(() => {
    onOpenChange?.(open || settingsOpen);
    return () => onOpenChange?.(false);
  }, [open, settingsOpen, onOpenChange]);
  useEffect(() => {
    onBusy(working);
    return () => onBusy(false);
  }, [working, onBusy]);
  useEffect(() => {
    let active = true;
    setAccounts([]);
    setError("");
    if (!uid) {
      setLoading(false);
      return;
    }
    setLoading(true);
    api<{ accounts: Choice[] }>(
      `/seasons/${season.id}/staff-signups/accounts?user_id=${encodeURIComponent(uid)}`,
    )
      .then((data) => {
        if (!active) return;
        setAccounts(data.accounts);
        setSelected((current) =>
          current.filter((tag) =>
            data.accounts.some(
              (account) => account.tag === tag && !account.signed_up_pool,
            ),
          ),
        );
      })
      .catch((cause) => {
        if (active)
          setError(
            cause instanceof Error ? cause.message : "Could not load accounts.",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [uid, season.id, reload]);

  const matching = accounts.filter((account) =>
    [account.name, account.tag, account.current_clan_name].some((value) =>
      value?.toLowerCase().includes(search.trim().toLowerCase()),
    ),
  );
  const unsigned = matching.filter((account) => !account.signed_up_pool);
  const canDiscard = () =>
    !working &&
    (!dirty ||
      window.confirm(
        "Discard this unfinished signup? Saved signups will stay unchanged.",
      ));
  const restoreAddFocus = () =>
    requestAnimationFrame(() =>
      addButton.current?.focus({ preventScroll: true }),
    );

  function reset() {
    setUid("");
    setPool("");
    setSelected([]);
    setSearch("");
    setTagDirty(false);
    setOpen(false);
  }
  function close() {
    reset();
    restoreAddFocus();
  }
  async function toggle() {
    if (working || disabled || archived || open || !canSettings) return;
    const action = season.signup_open ? "Close" : "Open";
    if (
      !window.confirm(
        `${action} Main and Lazy signups for ${season.label}? Existing signups will stay saved.`,
      )
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/seasons/${season.id}`, "PATCH", {
        signup_open: !season.signup_open,
      });
      setNotice(`Signups ${season.signup_open ? "closed" : "opened"}.`);
      await onChanged(false);
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not change signups.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function add() {
    if (
      working ||
      disabled ||
      loading ||
      error ||
      !uid ||
      !pool ||
      !selected.length ||
      archived
    )
      return;
    if (
      !window.confirm(
        `Add ${selected.length} accounts to ${pool === "main" ? "Main" : "Lazy"} CWL for the selected member?`,
      )
    )
      return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await api<{ count: number }>(
        `/seasons/${season.id}/staff-signups`,
        "POST",
        {
          user_id: uid,
          pool,
          accounts: selected.map((tag) => ({
            tag,
            prefer_crystal_1_or_lower: false,
          })),
        },
      );
      reset();
      setNotice(
        `${result.count} account${result.count === 1 ? "" : "s"} added to ${pool === "main" ? "Main" : "Lazy"} CWL. Assign a host in the roster below.`,
      );
      try {
        await onChanged(true);
      } catch {
        setError("Signup saved. Refresh the page to see the latest list.");
      }
      restoreAddFocus();
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not add signup.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="staff-signup-controls"
      aria-label="Staff signup controls"
    >
      <div className="staff-signup-bar">
        <StatusPill
          tone={
            archived ? "neutral" : season.signup_open ? "success" : "warning"
          }
        >
          {archived
            ? "Archived season"
            : season.signup_open
              ? "Signups open"
              : "Signups closed"}
        </StatusPill>
        <span className="staff-signup-bar-actions">
          {!archived && (
            <button
              ref={addButton}
              type="button"
              className="roster-ui roster-ui-button is-secondary"
              disabled={working || disabled || settingsOpen}
              onClick={() => {
                setError("");
                setOpen(true);
              }}
              aria-expanded={open}
            >
              <Plus size={17} aria-hidden="true" /> Add signup
            </button>
          )}
          {canSettings && !archived && (
            <button
              ref={settingsButton}
              type="button"
              className="roster-ui roster-ui-button is-icon"
              aria-label="Signup window settings"
              aria-expanded={settingsOpen}
              disabled={working || disabled || open}
              onClick={() => setSettingsOpen(true)}
            >
              <Settings2 size={18} aria-hidden="true" />
            </button>
          )}
        </span>
      </div>
      {settingsOpen && (
        <ActionPanel
          title="Signup window settings"
          className="roster-ui"
          trigger={settingsButton.current}
          busy={working}
          onClose={() => setSettingsOpen(false)}
        >
          <div className="staff-signup-window-panel">
            <StatusPill tone={season.signup_open ? "success" : "warning"}>
              {season.signup_open ? "Signups open" : "Signups closed"}
            </StatusPill>
            <p>
              Closing the window keeps saved signups. Staff can still add
              accounts.
            </p>
            <Button
              disabled={working || disabled}
              onClick={() => void toggle()}
            >
              {season.signup_open ? "Close signups" : "Open signups"}
            </Button>
            {error && (
              <p className="notice error" role="alert">
                {error}
              </p>
            )}
          </div>
        </ActionPanel>
      )}
      {notice && (
        <p className="notice success" role="status">
          {notice}
        </p>
      )}
      {open && (
        <ActionPanel
          title="Add signup"
          className="roster-ui"
          trigger={addButton.current}
          busy={working || editorOpen}
          expandOnSearchFocus
          onClose={() => {
            if (!canDiscard()) return false;
            close();
            return true;
          }}
        >
          <div className="staff-signup-form">
            <div className="section-heading">
              <h3>Choose how to add</h3>
              <Button
                icon={X}
                disabled={working}
                onClick={() => {
                  if (canDiscard()) close();
                }}
              >
                Cancel
              </Button>
            </div>
            <div
              className="workflow-tabs staff-add-modes"
              role="group"
              aria-label="How to add signup"
            >
              <button
                type="button"
                aria-pressed={mode === "tag"}
                disabled={working}
                onClick={() => {
                  if (mode !== "tag" && canDiscard()) {
                    reset();
                    setOpen(true);
                    setMode("tag");
                  }
                }}
              >
                By player tag
              </button>
              <button
                type="button"
                aria-pressed={mode === "member"}
                disabled={working}
                onClick={() => {
                  if (mode !== "member" && canDiscard()) {
                    reset();
                    setOpen(true);
                    setMode("member");
                  }
                }}
              >
                By Discord member
              </button>
            </div>
            {mode === "tag" ? (
              <StaffTagSignup
                seasonId={String(season.id)}
                onSaved={() => onChanged(true)}
                onDirty={setTagDirty}
                onBusy={setTagBusy}
              />
            ) : (
              <>
                <p>Choose a member and their linked accounts.</p>
                <fieldset disabled={busy || disabled}>
                  <MemberPicker
                    label="Member for signup"
                    value={uid}
                    onChange={(value) => {
                      if (
                        selected.length &&
                        !window.confirm(
                          "Change member and clear selected accounts?",
                        )
                      )
                        return;
                      setUid(String(value || ""));
                      setSelected([]);
                      setSearch("");
                    }}
                    disabled={busy}
                    endpoint="/staff-signup-members"
                    showRoles={false}
                  />
                  {uid && (
                    <>
                      <RosterMenu
                        label="CWL type"
                        value={pool}
                        disabled={busy || disabled}
                        onValueChange={(value) => setPool(value as Pool | "")}
                        options={[
                          { value: "", label: "Choose Main or Lazy" },
                          { value: "main", label: "Main CWL" },
                          { value: "lazy", label: "Lazy CWL" },
                        ]}
                      />
                      <div className="section-heading">
                        <h3>Linked accounts</h3>
                        <Button
                          icon={RotateCw}
                          disabled={loading || busy}
                          onClick={() => setReload((value) => value + 1)}
                        >
                          Reload accounts
                        </Button>
                      </div>
                      {loading ? (
                        <p role="status">Loading accounts…</p>
                      ) : !accounts.length ? (
                        <p>
                          {error
                            ? "Could not load accounts. Select Reload accounts to try again."
                            : "No linked accounts. Ask this member to use /link in Discord, then reload accounts."}
                        </p>
                      ) : (
                        <>
                          <Input
                            label="Find an account"
                            type="search"
                            value={search}
                            onChange={(event) => setSearch(event.target.value)}
                            placeholder="Account name, tag or clan"
                          />
                          <div className="staff-signup-list-tools">
                            <label className="check-label">
                              <input
                                type="checkbox"
                                checked={
                                  unsigned.length > 0 &&
                                  unsigned.every((account) =>
                                    selected.includes(account.tag),
                                  )
                                }
                                ref={(node) => {
                                  if (node)
                                    node.indeterminate =
                                      unsigned.some((account) =>
                                        selected.includes(account.tag),
                                      ) &&
                                      !unsigned.every((account) =>
                                        selected.includes(account.tag),
                                      );
                                }}
                                disabled={!unsigned.length || loading}
                                onChange={(event) =>
                                  setSelected((current) =>
                                    event.target.checked
                                      ? [
                                          ...new Set([
                                            ...current,
                                            ...unsigned.map(
                                              (account) => account.tag,
                                            ),
                                          ]),
                                        ]
                                      : current.filter(
                                          (tag) =>
                                            !unsigned.some(
                                              (account) => account.tag === tag,
                                            ),
                                        ),
                                  )
                                }
                              />
                              Select all matching accounts ({unsigned.length})
                            </label>
                            {selected.length > 0 && (
                              <Button icon={X} onClick={() => setSelected([])}>
                                Clear selection
                              </Button>
                            )}
                          </div>
                          {!matching.length && (
                            <p>No accounts match your search.</p>
                          )}
                          <div className="staff-signup-accounts">
                            {matching.map((account) => (
                              <div
                                className="staff-signup-account"
                                key={account.tag}
                              >
                                <label>
                                  <input
                                    type="checkbox"
                                    disabled={!!account.signed_up_pool || busy}
                                    checked={selected.includes(account.tag)}
                                    onChange={(event) =>
                                      setSelected((current) =>
                                        event.target.checked
                                          ? [...current, account.tag]
                                          : current.filter(
                                              (tag) => tag !== account.tag,
                                            ),
                                      )
                                    }
                                  />
                                  <TownHallIcon level={account.town_hall} />
                                  <span>
                                    <strong>{account.name}</strong>
                                    <small>
                                      {account.tag} ·{" "}
                                      {account.current_clan_name || "No clan"}
                                    </small>
                                    {account.signed_up_pool && (
                                      <small>
                                        Already signed up ·{" "}
                                        {account.signed_up_pool === "main"
                                          ? "Main"
                                          : "Lazy"}{" "}
                                        CWL
                                      </small>
                                    )}
                                  </span>
                                </label>
                                {account.signed_up_pool && (
                                  <StaffPlayerButton
                                    rosterUi
                                    onDirty={setEditorDirty}
                                    onBusy={setEditorBusy}
                                    onOpenChange={setEditorOpen}
                                    seasonId={String(season.id)}
                                    tag={account.tag}
                                    onChanged={async () => {
                                      setReload((value) => value + 1);
                                      await onChanged(true);
                                    }}
                                  >
                                    Account details
                                  </StaffPlayerButton>
                                )}
                              </div>
                            ))}
                          </div>
                        </>
                      )}
                      <div className="staff-signup-submit">
                        <strong>
                          {selected.length} selected
                          {pool
                            ? ` · ${pool === "main" ? "Main" : "Lazy"} CWL`
                            : ""}
                        </strong>
                        <Button
                          variant="primary"
                          icon={Plus}
                          disabled={
                            busy ||
                            loading ||
                            !!error ||
                            !pool ||
                            !selected.length
                          }
                          onClick={() => void add()}
                        >
                          {busy
                            ? "Saving…"
                            : `Add ${selected.length || ""} ${selected.length === 1 ? "account" : "accounts"}`}
                        </Button>
                      </div>
                    </>
                  )}
                </fieldset>
              </>
            )}
            {error && (
              <p className="notice error" role="alert">
                {error}
              </p>
            )}
          </div>
        </ActionPanel>
      )}
      {error && !open && !settingsOpen && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

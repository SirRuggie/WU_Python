import { relativeTime } from "./commandTime";
import ConfirmDialog from "./ConfirmDialog";
import CommandScope from "./CommandScope";
import type { AnnouncementChannel } from "./announcements";
import DeletedCommands from "./DeletedCommands";
import CommandTest from "./CommandTest";
import CommandActivity from "./CommandActivity";
import type { RoleChoice } from "./CommandExtras";
import MentionText, { namedMentions, type MentionNames } from "./MentionText";
import ChangeHistory from "./ChangeHistory";
import { useEffect, useState, useRef } from "react";
import { api, ApiError } from "./api";
import DiscordMessagePreview from "./DiscordMessagePreview";
import "./TextCommands.css";

import CommandBuilder, {
  hasRoleActions,
  commandBlocks,
  blockTextLength,
  commandPreview,
  mapBlockText,
  type Command,
} from "./CommandBuilder";
export { commandPreview } from "./CommandBuilder";
const blank = (): Command => ({
  command: "!",
  enabled: true,
  delete_trigger: true,
  text: "",
  title: "",
  description: "",
  image_url: "",
  color: "#e2b332",
  blocks: [],
  allow_pings: false,
  choose_recipient: false,
  recipient_ping: false,
});
const normalizeCommand = (row: Command): Command => ({
  ...row,
  delete_trigger: row.delete_trigger ?? true,
});

export default function TextCommands({
  onDirty,
}: {
  onDirty: (value: boolean) => void;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  const directory = useRef<HTMLHeadingElement>(null);
  const mutation = useRef(false);
  const sequence = useRef(0);
  const [conflict, setConflict] = useState(false);
  const [confirmation, setConfirmation] = useState<{
    text: string;
    action: () => void;
    danger?: boolean;
  } | null>(null);
  function closeEditor(confirmed = false) {
    if (busy || mutation.current) return;
    if (dirty && !confirmed) {
      setConfirmation({
        text: "Discard unsaved command changes?",
        action: () => closeEditor(true),
      });
      return;
    }
    setDraft(null);
    setSaved(null);
    setConflict(false);
    requestAnimationFrame(() => directory.current?.focus());
  }
  const [rows, setRows] = useState<Command[]>([]),
    [search, setSearch] = useState(""),
    [draft, setDraft] = useState<Command | null>(null),
    [saved, setSaved] = useState<Command | null>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [loading, setLoading] = useState(true),
    [pane, setPane] = useState<"edit" | "preview">("edit");
  const [roles, setRoles] = useState<RoleChoice[]>([]),
    [roleError, setRoleError] = useState("");
  const rolesLoaded = useRef(false),
    rolesLoading = useRef(false);
  async function loadRoles() {
    if (rolesLoading.current) return;
    rolesLoading.current = true;
    try {
      const data = await api<{ roles: RoleChoice[] }>(
        "/manage/text-command-roles",
      );
      setRoles(data.roles);
      setRoleError("");
      rolesLoaded.current = true;
    } catch {
      setRoleError("Could not load role choices.");
    } finally {
      rolesLoading.current = false;
    }
  }
  const [scope, setScope] = useState<{
    channels: AnnouncementChannel[];
    roles: RoleChoice[];
  }>({ channels: [], roles: [] });
  const [scopeError, setScopeError] = useState("");
  async function loadScope() {
    try {
      setScope(await api("/manage/text-command-scope"));
      setScopeError("");
    } catch {
      setScopeError("Could not load channel and role choices.");
    }
  }
  useEffect(() => {
    void loadScope();
  }, []);
  const deleteWarning = (error: NonNullable<Command["last_delete_error"]>) =>
    `Last time the bot could not delete the trigger message in ${scope.channels.find((c) => c.id === error.channel_id) ? "#" + scope.channels.find((c) => c.id === error.channel_id)!.name : "an unavailable channel"} (it needs Manage Messages there).`;
  const [mentionNames, setMentionNames] = useState<MentionNames>({});
  const rememberMention = (key: string, name: string) =>
    setMentionNames((current) =>
      current[key] === name ? current : { ...current, [key]: name },
    );
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(saved);
  async function load() {
    const turn = ++sequence.current;
    setLoading(true);
    try {
      const data = await api<{ commands: Command[] }>("/manage/text-commands");
      if (turn !== sequence.current) return;
      setRows(data.commands.map(normalizeCommand));
      setError("");
    } catch (e) {
      if (turn !== sequence.current) return;
      if (e instanceof ApiError && [401, 403].includes(e.status)) {
        setRows([]);
        setDraft(null);
        setSaved(null);
      }
      setError(e instanceof Error ? e.message : "Could not load commands.");
    } finally {
      if (turn === sequence.current) setLoading(false);
    }
  }
  useEffect(() => {
    void load();
    return () => {
      sequence.current++;
    };
  }, []);
  useEffect(() => {
    onDirty(dirty || busy);
    const guard = (e: BeforeUnloadEvent) => {
      if (dirty || busy) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", guard);
    return () => {
      onDirty(false);
      window.removeEventListener("beforeunload", guard);
    };
  }, [dirty, busy, onDirty]);
  function choose(row: Command | null, confirmed = false) {
    if (busy || loading || mutation.current) return;
    if (dirty && !confirmed) {
      setConfirmation({
        text: "Discard unsaved command changes?",
        action: () => choose(row, true),
      });
      return;
    }
    if (!rolesLoaded.current) void loadRoles();
    const selected = row ? normalizeCommand(row) : null;
    setSaved(selected);
    setDraft(selected ? { ...selected } : blank());
    setError("");
    setNotice("");
    setPane("edit");
    setConflict(false);
    requestAnimationFrame(() => heading.current?.focus());
  }
  function change(key: keyof Command, value: string | boolean) {
    setDraft((current) => (current ? { ...current, [key]: value } : current));
    setNotice("");
  }
  async function save() {
    if (!draft || busy || mutation.current || conflict) return;
    mutation.current = true;
    setBusy(true);
    setError("");
    try {
      const { revision, ...values } = draft;
      delete values.last_delete_error;
      delete values.use_count;
      delete values.last_used_at;
      delete values.last_outcome;
      const result = await api<Command>(
        "/manage/text-commands" +
          (saved ? "/" + encodeURIComponent(saved.command) : ""),
        saved ? "PATCH" : "POST",
        { values, revision },
      );
      setRows((current) =>
        [
          ...current.filter((row) => row.command !== result.command),
          normalizeCommand(result),
        ].sort((a, b) => a.command.localeCompare(b.command)),
      );
      setSaved(normalizeCommand(result));
      setDraft(normalizeCommand(result));
      setConflict(false);
      setNotice(
        result.enabled
          ? `${result.command} is ready to use in Discord.`
          : `${result.command} is saved and turned off.`,
      );
    } catch (e) {
      setConflict(e instanceof ApiError && e.status === 409);
      if (e instanceof ApiError && [401, 403].includes(e.status)) {
        setRows([]);
        setDraft(null);
        setSaved(null);
      }
      setError(
        e instanceof ApiError && e.status === 409
          ? "This command changed elsewhere. Your draft is kept. Reload commands to review the saved version."
          : e instanceof Error
            ? e.message
            : "Could not save command.",
      );
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  }
  async function remove(confirmed = false) {
    if (!saved || busy || mutation.current || conflict) return;
    if (!confirmed) {
      setConfirmation({
        text: `Delete ${saved.command}? Its reply will be removed.`,
        danger: true,
        action: () => void remove(true),
      });
      return;
    }
    mutation.current = true;
    setBusy(true);
    setError("");
    try {
      await api(
        "/manage/text-commands/" + encodeURIComponent(saved.command),
        "DELETE",
        { revision: saved.revision },
      );
      setRows((current) =>
        current.filter((row) => row.command !== saved.command),
      );
      setDraft(null);
      setSaved(null);
      setNotice("Command deleted.");
      requestAnimationFrame(() => directory.current?.focus());
    } catch (e) {
      if (e instanceof ApiError && [401, 403].includes(e.status)) {
        setRows([]);
        setDraft(null);
        setSaved(null);
      }
      setError(e instanceof Error ? e.message : "Could not delete command.");
    } finally {
      mutation.current = false;
      setBusy(false);
    }
  }
  return (
    <section className={`text-commands ${draft ? "command-is-editing" : ""}`}>
      {confirmation && (
        <ConfirmDialog
          text={confirmation.text}
          danger={confirmation.danger}
          confirmLabel={
            confirmation.danger ? "Delete command" : "Discard changes"
          }
          onCancel={() => setConfirmation(null)}
          onConfirm={() => {
            const action = confirmation.action;
            setConfirmation(null);
            action();
          }}
        />
      )}
      <div className="page-head">
        <div>
          <p className="eyebrow">SERVER TOOLS</p>
          <h1>Command triggers</h1>
          <p>
            Type a command like <strong>!rules</strong> in Discord. The bot
            posts its reply.
          </p>
        </div>
        <button
          className="primary"
          disabled={busy || loading}
          onClick={() => choose(null)}
        >
          + New command
        </button>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
          <button
            disabled={busy}
            onClick={async () => {
              const reload = () => {
                setDraft(null);
                setSaved(null);
                void load();
              };
              if (dirty)
                setConfirmation({
                  text: "Discard edits and reload commands?",
                  action: reload,
                });
              else reload();
            }}
          >
            Reload commands
          </button>
        </div>
      )}
      {notice && (
        <p className="notice" role="status">
          {notice}
        </p>
      )}
      <div className="text-command-workspace">
        <aside className="card text-command-list">
          <h2 ref={directory} tabIndex={-1}>
            Saved commands
          </h2>
          <p className="small">
            {rows.length} commands · {rows.filter((row) => row.enabled).length}{" "}
            enabled
          </p>
          <label>
            Find a command
            <input
              type="search"
              placeholder="!trigger"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          {loading ? (
            <p role="status">Loading commands…</p>
          ) : error && rows.length === 0 ? (
            <p>Commands could not be loaded. Use Reload commands above.</p>
          ) : rows.length === 0 ? (
            <p>No commands yet. Select New command.</p>
          ) : (
            <div className="text-command-rows">
              {rows
                .filter((row) =>
                  row.command.includes(search.trim().toLowerCase()),
                )
                .map((row) => (
                  <button
                    key={row.command}
                    disabled={busy}
                    aria-pressed={saved?.command === row.command}
                    onClick={() => choose(row)}
                  >
                    <span className="text-command-row-info">
                      <strong>{row.command}</strong>
                      <small>
                        Used {row.use_count ?? 0}{" "}
                        {(row.use_count ?? 0) === 1 ? "time" : "times"} · last{" "}
                        {relativeTime(row.last_used_at)}
                      </small>
                      {row.last_delete_error && (
                        <small>{deleteWarning(row.last_delete_error)}</small>
                      )}
                    </span>
                    <span>{row.enabled ? "On" : "Off"}</span>
                  </button>
                ))}
              {rows.length > 0 &&
                !rows.some((row) =>
                  row.command.includes(search.trim().toLowerCase()),
                ) && <p>No matching commands.</p>}
            </div>
          )}
          <DeletedCommands
            disabled={busy || dirty}
            onBusy={setBusy}
            onRestored={load}
          />
        </aside>
        {draft ? (
          <section>
            <div className="command-editor-heading">
              <h2 ref={heading} tabIndex={-1}>
                {saved ? saved.command : "New command"}
              </h2>
              <button
                type="button"
                disabled={busy}
                onClick={() => closeEditor()}
                aria-label="Back to commands"
              >
                ← Commands
              </button>
            </div>
            {draft.last_outcome && (
              <p role="status">
                {draft.last_outcome.status === "ok"
                  ? "Last reply sent"
                  : "Last failed"}{" "}
                {relativeTime(draft.last_outcome.at)}
                {draft.last_outcome.reason
                  ? ` · ${draft.last_outcome.reason}`
                  : ""}
              </p>
            )}
            {draft.last_delete_error && (
              <p className="notice error command-delete-warning" role="alert">
                {deleteWarning(draft.last_delete_error)}
              </p>
            )}
            <div
              className="text-command-tabs"
              role="group"
              aria-label="Command editor view"
            >
              <button
                aria-pressed={pane === "edit"}
                onClick={() => setPane("edit")}
              >
                Edit reply
              </button>
              <button
                aria-pressed={pane === "preview"}
                onClick={() => setPane("preview")}
              >
                Preview
              </button>
            </div>
            <div className={`text-command-editor mobile-${pane}`}>
              <form
                className="card"
                id="command-reply-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void save();
                }}
              >
                <fieldset disabled={busy}>
                  <legend className="command-sr-only">
                    {saved ? "Edit " + saved.command : "New command"}
                  </legend>
                  <details open key={draft.command + ":command"}>
                    <summary>
                      Command · {draft.command} · {draft.enabled ? "On" : "Off"}
                    </summary>
                    <label>
                      Command
                      <input
                        value={draft.command}
                        readOnly={!!saved}
                        required
                        pattern={"![a-zA-Z0-9][a-zA-Z0-9_\\-]{0,31}"}
                        maxLength={33}
                        placeholder="!trigger"
                        onChange={(e) => change("command", e.target.value)}
                      />
                      <small>
                        One word starting with !. Uppercase and lowercase work
                        the same.
                      </small>
                    </label>
                    <label className="text-command-enable">
                      <input
                        type="checkbox"
                        checked={draft.enabled}
                        onChange={(e) => change("enabled", e.target.checked)}
                      />
                      On
                    </label>
                    <label className="text-command-enable">
                      <input
                        type="checkbox"
                        checked={draft.delete_trigger ?? true}
                        onChange={(e) =>
                          change("delete_trigger", e.target.checked)
                        }
                      />
                      Delete the trigger message
                    </label>
                    {scopeError ? (
                      <p role="alert">
                        {scopeError}{" "}
                        <button type="button" onClick={() => void loadScope()}>
                          Retry choices
                        </button>
                      </p>
                    ) : (
                      <CommandScope
                        draft={draft}
                        channels={scope.channels}
                        roles={scope.roles}
                        disabled={busy}
                        onChange={(key, values) =>
                          setDraft((current) =>
                            current ? { ...current, [key]: values } : current,
                          )
                        }
                      />
                    )}
                  </details>
                  <details key={draft.command + ":reply"}>
                    <summary>
                      Reply · {commandBlocks(draft).length} blocks ·{" "}
                      {(
                        draft.text.length +
                        commandBlocks(draft).reduce(
                          (sum, block) => sum + blockTextLength(block),
                          0,
                        )
                      ).toLocaleString()}
                      /4,000 characters
                    </summary>
                    <MentionText
                      key={draft.command}
                      label="Text above the card"
                      value={draft.text}
                      maxLength={2000}
                      placeholder="Text shown above the embed…"
                      onChange={(text) => change("text", text)}
                      onMention={rememberMention}
                    />

                    {roleError && (
                      <p role="status">
                        {roleError}{" "}
                        <button type="button" onClick={() => void loadRoles()}>
                          Retry roles
                        </button>
                      </p>
                    )}
                    <CommandBuilder
                      roles={roles}
                      commands={rows
                        .filter((row) => row.enabled)
                        .map((row) => row.command)}
                      onBusy={setBusy}
                      key={draft.command + ":" + (draft.revision || "new")}
                      onMention={rememberMention}
                      value={draft}
                      onChange={(blocks) => {
                        setDraft((current) =>
                          current
                            ? {
                                ...current,
                                blocks,
                                title: "",
                                description: "",
                                image_url: "",
                              }
                            : current,
                        );
                        setNotice("");
                      }}
                    />
                  </details>
                  <details className="command-recipient-settings">
                    <summary>
                      Pings ·{" "}
                      {draft.allow_pings || draft.choose_recipient
                        ? "On"
                        : "Off"}
                    </summary>
                    <label className="text-command-enable">
                      <input
                        type="checkbox"
                        checked={draft.allow_pings ?? false}
                        onChange={(e) =>
                          change("allow_pings", e.target.checked)
                        }
                      />
                      Ping the people and roles in this reply
                    </label>
                    <small>
                      Pings the roles and users you add to the reply, including
                      @here and @everyone.
                    </small>
                    <hr />
                    <label className="text-command-enable">
                      <input
                        type="checkbox"
                        checked={draft.choose_recipient ?? false}
                        onChange={(e) =>
                          change("choose_recipient", e.target.checked)
                        }
                      />
                      Let members add @person or @role
                    </label>
                    <small>
                      Type !trigger @person or !trigger @role. Pings inside the
                      embed, or above the text if there is no embed.
                    </small>
                  </details>
                  <details className="command-appearance">
                    <summary>Look · {draft.color}</summary>{" "}
                    <div className="command-color">
                      <label>
                        Embed color
                        <input
                          type="color"
                          value={
                            /^#[0-9a-f]{6}$/i.test(draft.color)
                              ? draft.color
                              : "#e2b332"
                          }
                          onChange={(e) => change("color", e.target.value)}
                        />
                      </label>
                      <label>
                        Hex color
                        <input
                          type="text"
                          value={draft.color}
                          maxLength={7}
                          pattern="#[0-9a-fA-F]{6}"
                          required
                          placeholder="#E2B332"
                          spellCheck={false}
                          aria-invalid={!/^#[0-9a-f]{6}$/i.test(draft.color)}
                          onChange={(e) =>
                            change(
                              "color",
                              e.target.value.startsWith("#")
                                ? e.target.value
                                : "#" + e.target.value,
                            )
                          }
                        />
                      </label>
                    </div>
                    {!/^#[0-9a-f]{6}$/i.test(draft.color) && (
                      <small role="status">
                        Enter # and six letters or numbers, for example #E2B332.
                      </small>
                    )}
                  </details>
                  <p className="small">
                    The reply appears in the same channel.
                  </p>
                </fieldset>
              </form>
              {pane === "preview" && (
                <DiscordMessagePreview
                  parts={commandPreview({
                    ...draft,
                    text: namedMentions(draft.text, mentionNames),
                    blocks: commandBlocks(draft).map((block) =>
                      mapBlockText(block, (text) =>
                        namedMentions(text, mentionNames),
                      ),
                    ),
                  })}
                  caption={
                    draft.choose_recipient
                      ? "The mention goes inside the embed, or above the text if there is no embed. Saving does not post."
                      : "Preview only. Saving does not post a message."
                  }
                />
              )}
            </div>
            <div className="text-command-save" aria-label="Save command">
              <span role="status">
                {busy ? "Working…" : dirty ? "Unsaved changes" : "Saved"}
              </span>
              <button
                type="button"
                className="primary"
                disabled={busy || !dirty || conflict}
                onClick={() => {
                  setPane("edit");
                  requestAnimationFrame(
                    () =>
                      document.getElementById("command-reply-form") &&
                      (
                        document.getElementById(
                          "command-reply-form",
                        ) as HTMLFormElement
                      ).requestSubmit(),
                  );
                }}
              >
                Save command
              </button>
            </div>
            <CommandTest draft={draft} disabled={busy} onBusy={setBusy} />
            {saved && hasRoleActions(commandBlocks(saved)) && (
              <CommandActivity
                key={"activity:" + saved.command}
                command={saved.command}
              />
            )}
            {saved?.revision && (
              <ChangeHistory
                onBusy={setBusy}
                key={"history:" + saved.command}
                target={
                  "/manage/text-commands/" + encodeURIComponent(saved.command)
                }
                revision={saved.revision}
                disabled={busy || dirty}
                labels={{
                  text: "Reply message",
                  title: "Card title",
                  description: "Card text",
                  image_url: "Card image",
                  color: "Card color",
                  enabled: "Enabled",
                  delete_trigger: "Delete the trigger message",
                }}
                onRestored={async () => {
                  const data = await api<{ commands: Command[] }>(
                    "/manage/text-commands",
                  );
                  setRows(data.commands.map(normalizeCommand));
                  const row =
                    data.commands.find(
                      (item) => item.command === saved.command,
                    ) || null;
                  setSaved(row ? normalizeCommand(row) : null);
                  setDraft(row ? normalizeCommand(row) : null);
                }}
              />
            )}
            {saved && (
              <details className="command-danger">
                <summary>Danger zone</summary>
                <p>
                  Removes the saved reply. Existing Discord posts stay in place.
                </p>
                <button
                  type="button"
                  disabled={busy || dirty || conflict}
                  onClick={() => void remove()}
                >
                  Delete {saved.command}
                </button>
                {dirty && <p>Save or discard your edits first.</p>}
              </details>
            )}
          </section>
        ) : (
          <section className="card">
            <h2>Create a saved reply</h2>
            <p>Choose New command or select a command to edit.</p>
            <p className="small">Example: !trigger → your saved reply.</p>
          </section>
        )}
      </div>
    </section>
  );
}

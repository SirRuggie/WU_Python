import SignupDateField from "./reminders/SignupDateField";
import ConfirmDialog from "./ConfirmDialog";
import { useReminderLookup } from "./useReminderLookups";
import DiscordPreview, { type PreviewPart } from "./DiscordMessagePreview";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ApiError, type Pool } from "./api";
import ChannelCombobox from "./ChannelCombobox";
import type { AnnouncementChannel } from "./announcements";
import {
  campaignPatch,
  displayTime,
  nextReminderOccurrence,
  type Campaign,
  type CampaignState,
  type Timing,
  type Variant,
} from "./reminderCampaign";
import "./ReminderWorkspace.css";
const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Request failed. Try again.";
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value));

function TimingEditor({
  value,
  onChange,
  deadline = false,
}: {
  value: Timing | string;
  onChange: (value: Timing) => void;
  deadline?: boolean;
}) {
  const rule: Timing = typeof value === "string" ? { at: value } : value;
  const mode = deadline
    ? rule.at
      ? "specific"
      : "monthly"
    : rule.mode || "manual";
  const update = (patch: Timing) => onChange({ ...rule, ...patch });
  return (
    <div className="reminder-fields">
      <label>
        Timing
        <select
          value={mode}
          onChange={(event) =>
            onChange(
              event.target.value === "specific"
                ? { ...(deadline ? {} : { mode: "specific" }), at: "" }
                : event.target.value === "monthly"
                  ? {
                      ...(deadline ? {} : { mode: "monthly" }),
                      day: 1,
                      hour: 17,
                      minute: 0,
                    }
                  : {
                      mode: event.target.value,
                      ...(event.target.value === "manual"
                        ? {}
                        : { offset_minutes: 1440 }),
                    },
            )
          }
        >
          {!deadline && <option value="manual">Manual only</option>}
          <option value="specific">Specific date and time</option>
          <option value="monthly">Monthly date rule</option>
          {!deadline && (
            <>
              <option value="after_open">After signup opens</option>
              <option value="before_close">Before signup closes</option>
              {mode === "legacy_chain" && (
                <option value="legacy_chain">
                  After previous message (existing)
                </option>
              )}
            </>
          )}
        </select>
      </label>
      {mode === "specific" && (
        <label>
          Date and time
          <input
            type="datetime-local"
            value={(rule.at || "").slice(0, 16)}
            onChange={(event) => update({ at: event.target.value })}
          />
          <small>Uses the schedule timezone.</small>
        </label>
      )}
      {mode === "monthly" && (
        <>
          <label>
            Count from
            <select
              value={rule.month_end_offset_days !== undefined ? "end" : "day"}
              onChange={(event) => {
                const next = { ...rule };
                delete next.day;
                delete next.month_end_offset_days;
                onChange({
                  ...next,
                  ...(event.target.value === "end"
                    ? { month_end_offset_days: 2 }
                    : { day: 1 }),
                });
              }}
            >
              <option value="day">Day of month</option>
              <option value="end">Days before month ends</option>
            </select>
          </label>
          <label>
            {rule.month_end_offset_days !== undefined
              ? "Days before month ends"
              : "Day of month"}
            <input
              type="number"
              min={rule.month_end_offset_days !== undefined ? 0 : 1}
              max={rule.month_end_offset_days !== undefined ? 27 : 31}
              value={rule.month_end_offset_days ?? rule.day ?? 1}
              onChange={(event) =>
                update({
                  [rule.month_end_offset_days !== undefined
                    ? "month_end_offset_days"
                    : "day"]: Number(event.target.value),
                })
              }
            />
          </label>
          <label>
            Time
            <input
              type="time"
              value={`${String(rule.hour ?? 17).padStart(2, "0")}:${String(rule.minute ?? 0).padStart(2, "0")}`}
              onChange={(event) => {
                const [hour, minute] = event.target.value
                  .split(":")
                  .map(Number);
                update({ hour, minute });
              }}
            />
          </label>

        </>
      )}
      {["after_open", "before_close", "legacy_chain"].includes(mode) && (
        <label>
          Offset in minutes
          <input
            type="number"
            min={0}
            value={rule.offset_minutes ?? 1440}
            onChange={(event) =>
              update({ offset_minutes: Number(event.target.value) })
            }
          />
          {mode === "legacy_chain" && (
            <small>After {rule.after || "previous reminder"}.</small>
          )}
        </label>
      )}
    </div>
  );
}

function MessagePreview({children}: {children: ReactNode}) {
  const [open, setOpen] = useState(false);
  return <details className="reminder-disclosure" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>Discord preview</summary>
    {open && children}
  </details>;
}

export default function ReminderWorkspace({
  seasonId,
  archived,
  onDirty,
}: {
  seasonId: string;
  archived: boolean;
  onDirty: (dirty: boolean) => void;
}) {
  const base = `/seasons/${encodeURIComponent(seasonId)}/manage-reminders`;
  const [state, setState] = useState<CampaignState | null>(null);
  const [draft, setDraft] = useState<Campaign | null>(null);
  const [preview, setPreview] = useState<CampaignState | null>(null);
  const channelLookup = useReminderLookup<AnnouncementChannel>(
    "/announcement-channels",
    "channels",
  );
  const roleLookup = useReminderLookup<{ id: string; name: string }>(
    "/announcement-roles",
    "roles",
  );
  const channels = channelLookup.items,
    roles = roleLookup.items;
  const channelError = channelLookup.error;
  const acting = useRef(false);
  const loadRequest = useRef(0);
  const [tab, setTab] = useState<"overview" | "messages" | "schedule" | "history">(
    "overview",
  );
  const [messageId, setMessageId] = useState("signup");
  const [pool, setPool] = useState<Pool>("main");
  const [roleText, setRoleText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmation, setConfirmation] = useState<{
    text: string;
    action: () => void;
  } | null>(null);
  const load = useCallback(async () => {
    const request = ++loadRequest.current;
    try {
      const data = await api<CampaignState>(base);
      if (request !== loadRequest.current) return;
      setState(data);
      setDraft(data.campaign ? clone(data.campaign) : null);
      setPreview(null);
    } catch (cause) {
      if (request === loadRequest.current && cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setState(null);
        setDraft(null);
        setPreview(null);
      }
      throw cause;
    }
  }, [base]);
  useEffect(() => {
    let alive = true;
    const request = ++loadRequest.current;
    setState(null);
    setDraft(null);
    setPreview(null);
    setError("");
    setBusy(true);
    api<CampaignState>(base)
      .then((data) => {
        if (!alive || request !== loadRequest.current) return;
        setState(data);
        setDraft(data.campaign ? clone(data.campaign) : null);
      })
      .catch((cause) => {
        if (!alive || request !== loadRequest.current) return;
        setError(errorText(cause));
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
          setState(null);
          setDraft(null);
        }
      })
      .finally(() => {
        if (alive && request === loadRequest.current) setBusy(false);
      });
    return () => {
      alive = false;
      loadRequest.current += 1;
    };
  }, [base]);
  const patch =
    state?.campaign && draft ? campaignPatch(state.campaign, draft) : {};
  const dirty = Object.keys(patch).length > 0;
  const protectedBusy = busy && !!state;
  useEffect(() => {
    onDirty(dirty || protectedBusy);
    return () => onDirty(false);
  }, [dirty, protectedBusy, onDirty]);
  useEffect(() => {
    setRoleText(
      draft?.messages[messageId]?.variants[pool]?.role_ids.join(", ") || "",
    );
  }, [messageId, pool, state]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    if (!state?.cycle || state.schedule_synced || busy) return;
    let active = true;
    const timer = window.setTimeout(() => {
      api<CampaignState>(base)
        .then(data => {
          if (!active) return;
          setState(current => current && data.generation === current.generation
            ? { ...current, worker_ready: data.worker_ready,
                schedule_synced: data.schedule_synced, schedule_sync_at: data.schedule_sync_at }
            : current);
        })
        .catch(cause => {
          if (!active || !(cause instanceof ApiError) || ![401, 403].includes(cause.status)) return;
          setState(null);
          setDraft(null);
          setPreview(null);
          setError(errorText(cause));
        });
    }, 10000);
    return () => { active = false; window.clearTimeout(timer); };
  }, [base, state, busy]);
  const act = async (work: () => Promise<void>) => {
    if (acting.current) return;
    acting.current = true;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (cause) {
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setState(null);
        setDraft(null);
        setPreview(null);
      }
      setError(errorText(cause));
    } finally {
      acting.current = false;
      setBusy(false);
    }
  };
  const edit = (next: Campaign) => {
    setDraft(next);
    setError("");
    setPreview(null);
    setNotice("");
  };
  const changeVariant = (change: Partial<Variant>) => {
    if (!draft) return;
    const next = clone(draft);
    Object.assign(next.messages[messageId].variants[pool], change);
    edit(next);
  };
  const body = { generation: state?.generation, patch, repeat_monthly: true };
  const selected = draft?.messages[messageId];
  const variant = selected?.variants[pool];
  const disabled = busy || archived;
  const schedule = preview?.schedule || state?.schedule || [];
  const destination = (id: string) => {
    if (!id) return "No channel chosen";
    return channels.find(channel => channel.id === id)?.name || `Channel ${id}`;
  };
  const recipient = (ids: string[]) => {
    if (!ids.length) return "No role mentions";
    const labels = ids.slice(0, 2).map(id => roles.find(role => role.id === id)?.name || `Role ${id}`);
    return `${labels.join(", ")}${ids.length > 2 ? ` +${ids.length - 2} more` : ""}`;
  };
  return (
    <section className="reminders-workspace">
      {error && (
        <p className="notice error" role="alert">
          {error}
          {!state && <button onClick={() => void act(load)} disabled={busy}>Retry loading reminders</button>}
        </p>
      )}
      {notice && (
        <p className="notice success" role="status">
          {notice}
        </p>
      )}
      {busy && <p role="status">Working…</p>}
      {state?.warning && <p className="notice error" role="alert">{state.warning}</p>}
      {state && (
        <>
          {draft && (
            <>
              <div className="reminder-status">
                <span className="badge">
                  {draft.paused
                    ? "Reminders paused"
                    : state.activated
                      ? "Automation enabled"
                      : "Not activated"}
                </span>
                <span>
                  {state.worker_ready ? "Bot online" : "Bot unavailable"}
                </span>
                <span role="status">
                  {state.schedule_synced
                    ? "Bot has loaded this schedule"
                    : "Waiting for the bot to load changes"}
                </span>
                <div className="reminder-control-actions">
                  <button
                    disabled={busy}
                    onClick={() => {
                      if (!dirty) void act(load);
                      else
                        setConfirmation({
                          text: "Discard unsaved reminder edits and refresh from Manage?",
                          action: () => void act(load),
                        });
                    }}
                  >
                    Refresh
                  </button>
                <button
                  disabled={disabled || dirty}
                  onClick={() => {
                    setConfirmation({
                      text: `${draft.paused ? "Resume" : "Pause"} the shared Manage CWL settings? This affects its scheduled messages in Discord too.`,
                      action: () =>
                        void act(async () => {
                          const paused = !draft.paused;
                          await api(base + "/pause", "POST", {
                            generation: state.generation,
                            paused,
                          });
                          await load();
                          setNotice(
                            paused
                              ? "Scheduled messages paused."
                              : "Scheduled messages resumed. The bot is updating its schedule.",
                          );
                        }),
                    });
                  }}
                >
                  {draft.paused ? "Resume reminders" : "Pause reminders"}
                </button>
                </div>
              </div>
              {archived && (
                <p className="notice">
                  This season is archived. Settings are read-only.
                </p>
              )}
              <div className="tabs workflow-tabs" role="group" aria-label="Reminder sections">
                {(["overview", "messages", "schedule", "history"] as const).map((value) => (
                  <button
                    key={value}
                    className={tab === value ? "active" : ""}
                    aria-pressed={tab === value}
                    onClick={() => setTab(value)}
                  >
                    {value === "overview"
                      ? "Overview"
                      : value === "messages"
                        ? "Messages"
                      : value === "schedule"
                        ? "Schedule"
                        : "Delivery history"}
                  </button>
                ))}
              </div>
              {tab === "overview" && <div className="reminder-overview">
                <div className="reminder-overview-head">
                  <h3>Messages · {state.cycle}</h3>
                  <button type="button" onClick={() => setTab("schedule")}>Edit timing</button>
                </div>
                <div className="reminder-overview-list">
                  {Object.entries(draft.messages).filter(([id]) => id !== "roster").flatMap(([id, item]) =>
                    (["main", "lazy"] as const).map(audience => {
                      const settings = item.variants[audience];
                      const upcoming = nextReminderOccurrence(schedule, id, audience);
                      const enabled = item.enabled && settings.enabled !== false;
                      return <article className="reminder-overview-row" key={`${id}:${audience}`}>
                        <div><strong>{item.label || id}</strong><small>{audience === "main" ? "Main Clan CWL" : "Lazy CWL"} · {enabled ? draft.paused ? "Paused" : "Enabled" : "Disabled"}</small></div>
                        <div><small>Destination</small><span>{destination(settings.destination_channel_id)}</span></div>
                        <div><small>Notify</small><span>{recipient(settings.role_ids)}</span></div>
                        <div><small>Next scheduled</small><span>{!enabled ? "Disabled" : upcoming?.run_at ? displayTime(upcoming.run_at) : "No upcoming send"}</span></div>
                        <button type="button" onClick={() => { setMessageId(id); setPool(audience); setTab("messages"); }}>Edit<span className="reminder-visually-hidden"> {item.label || id} for {audience === "main" ? "Main" : "Lazy"} CWL</span></button>
                      </article>;
                    }))}
                </div>
                {(channelError || roleLookup.error) && <p className="reminder-lookup-warning" role="status">Channel or role names are unavailable. IDs are shown; open a message to retry the lookup.</p>}
                <p className="reminder-overview-note">Scheduled times show the next planned send; delivery is confirmed in Delivery history. Website signups are {state.signup_open ? "open" : "closed"} separately.</p>
              </div>}
              {tab === "messages" && (
                <>
                  <div className="reminder-editor-intro">
                    <div
                      className="tabs workflow-tabs"
                      role="group"
                      aria-label="Message audience"
                    >
                      {(["main", "lazy"] as const).map((value) => (
                        <button
                          key={value}
                          className={pool === value ? "active" : ""}
                          aria-pressed={pool === value}
                          onClick={() => setPool(value)}
                        >
                          {value === "main" ? "Main Clan CWL" : "Lazy CWL"}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="reminder-fields">
                    <label>
                      Message to edit
                      <select
                        value={messageId}
                        onChange={(event) => setMessageId(event.target.value)}
                      >
                        {Object.entries(draft.messages)
                          .filter(([id]) => id !== "roster")
                          .map(([id, item]) => (
                            <option key={id} value={id}>
                              {item.label || id}
                            </option>
                          ))}
                      </select>
                    </label>
                  </div>
                  {selected && variant && (
                    <div className="reminder-columns">
                      <div className="card">
                        <fieldset disabled={disabled}>
                          <legend>
                            Edit {pool === "main" ? "Main" : "Lazy"} ·{" "}
                            {selected.label || messageId}
                          </legend>
                          <label className="check-label">
                            <input
                              type="checkbox"
                              checked={selected.enabled}
                              onChange={(event) => {
                                const next = clone(draft);
                                next.messages[messageId].enabled =
                                  event.target.checked;
                                edit(next);
                              }}
                            />
                            Enable this message
                          </label>
                          <label className="check-label">
                            <input
                              type="checkbox"
                              checked={variant.enabled !== false}
                              onChange={(event) =>
                                changeVariant({ enabled: event.target.checked })
                              }
                            />
                            Enable {pool === "main" ? "Main" : "Lazy"} version
                          </label>
                          {(channelError || roleLookup.error) && <p role="alert">Delivery settings need attention. Open Delivery settings below to retry the failed lookup.</p>}
                          <details className="reminder-disclosure">
                            <summary>Delivery settings · {variant.role_ids.length} {variant.role_ids.length === 1 ? "role" : "roles"} to notify</summary>
                          <ChannelCombobox
                            label="Destination channel"
                            channels={channels}
                            value={variant.destination_channel_id}
                            disabled={
                              disabled ||
                              channelLookup.loading ||
                              !!channelError
                            }
                            onChange={(value) =>
                              changeVariant({ destination_channel_id: value })
                            }
                          />
                          {channelLookup.loading && (
                            <p role="status">Loading channels…</p>
                          )}
                          {channelError && (
                            <div role="alert">
                              <p>Channels unavailable: {channelError}</p>
                              <button
                                type="button"
                                onClick={channelLookup.retry}
                              >
                                Retry channels
                              </button>
                            </div>
                          )}
                          <label>
                            Add a role
                            <select
                              disabled={
                                roleLookup.loading || !!roleLookup.error
                              }
                              value=""
                              onChange={(event) => {
                                if (!event.target.value) return;
                                const next = [
                                  ...new Set([
                                    ...variant.role_ids,
                                    event.target.value,
                                  ]),
                                ];
                                setRoleText(next.join(", "));
                                changeVariant({ role_ids: next });
                              }}
                            >
                              <option value="">Choose a server role</option>
                              {roles.map((role) => (
                                <option key={role.id} value={role.id}>
                                  {role.name}
                                </option>
                              ))}
                            </select>
                          </label>
                          {roleLookup.loading && (
                            <p role="status">Loading roles…</p>
                          )}
                          {roleLookup.error && (
                            <div role="alert">
                              <p>Roles unavailable: {roleLookup.error}</p>
                              <button type="button" onClick={roleLookup.retry}>
                                Retry roles
                              </button>
                            </div>
                          )}
                          <div
                            className="reminder-selected-roles"
                            aria-label="Roles to notify"
                          >
                            {variant.role_ids.length ? (
                              variant.role_ids.map((id) => (
                                <button
                                  type="button"
                                  key={id}
                                  aria-label={`Remove ${roles.find((role) => role.id === id)?.name || id}`}
                                  onClick={() => {
                                    const next = variant.role_ids.filter(
                                      (value) => value !== id,
                                    );
                                    setRoleText(next.join(", "));
                                    changeVariant({ role_ids: next });
                                  }}
                                >
                                  {roles.find((role) => role.id === id)?.name ||
                                    `Role ${id}`}{" "}
                                  ×
                                </button>
                              ))
                            ) : (
                              <p className="small">
                                No roles selected for notification.
                              </p>
                            )}
                          </div>
                          <details>
                            <summary>Advanced role settings</summary>
                            <label>
                              Role IDs to mention
                              <input
                                value={roleText}
                                onChange={(event) => {
                                  setRoleText(event.target.value);
                                  changeVariant({
                                    role_ids: [
                                      ...new Set(
                                        event.target.value
                                          .split(/[\s,]+/)
                                          .filter(Boolean),
                                      ),
                                    ],
                                  });
                                }}
                                placeholder="Separate Discord role IDs with commas"
                              />
                              <small>
                                These roles are notified when the bot sends this
                                message.
                              </small>
                            </label>
                          </details>
                          </details>
                          <label>
                            Title
                            <input
                              maxLength={4000}
                              value={variant.title}
                              onChange={(event) =>
                                changeVariant({ title: event.target.value })
                              }
                            />
                          </label>
                          <label>
                            Message
                            <textarea
                              rows={9}
                              maxLength={4000}
                              value={variant.body}
                              onChange={(event) =>
                                changeVariant({ body: event.target.value })
                              }
                            />
                            <small>
                              Discord formatting is supported. Use{" "}
                              {"{signup_deadline}"} for the shared closing date.
                            </small>
                          </label>
                          <details className="reminder-disclosure">
                            <summary>Message image</summary>
                          <label>
                            Image URL
                            <input
                              type="url"
                              value={variant.media_url || ""}
                              onChange={(event) =>
                                changeVariant({ media_url: event.target.value })
                              }
                            />
                          </label>
                          </details>
                        </fieldset>
                      </div>
                      <MessagePreview key={messageId+pool}><DiscordPreview
                        parts={[
                          {
                            type: "container",
                            children: [
                              { type: "text", text: "## " + variant.title },
                              {
                                type: "text",
                                text: variant.body.replaceAll(
                                  "{signup_deadline}",
                                  displayTime(
                                    preview?.deadline || state.deadline,
                                  ),
                                ),
                              },
                              ...(variant.media_url
                                ? [
                                    {
                                      type: "media",
                                      items: [
                                        {
                                          url: variant.media_url,
                                          description: "Announcement image",
                                        },
                                      ],
                                    } as PreviewPart,
                                  ]
                                : []),
                              {
                                type: "row",
                                children: variant.buttons.map((button) => ({
                                  type: "button",
                                  label: button.label,
                                  emoji: button.emoji,
                                  url: button.url,
                                })),
                              },
                            ],
                          },
                        ]}
                        caption="Discord preview. Signup buttons cannot be changed here."
                      /></MessagePreview>
                    </div>
                  )}
                </>
              )}
              {tab === "schedule" && (
                <div className="card">
                  <h3>Signup Reminders</h3>
                  <p>
                    Choose when Discord announces signups, the advertised deadline,
                    and how often reminders are sent.
                  </p>
                  <fieldset disabled={disabled}>
                    <legend>Signup window &amp; reminder timing</legend>
                    <p className="small">All dates and times below use {draft.timezone}. Current campaign: {state.cycle}.</p>
                    <div className="signup-date-grid">
                    <SignupDateField label="Opening announcement" value={draft.messages.signup.schedule}
                      cycle={state.cycle} timezone={draft.timezone}
                      onChange={value => {const next=clone(draft); next.messages.signup.schedule=value; edit(next)}}/>
                    <SignupDateField label="Advertised signup deadline" deadline value={draft.signup_deadline}
                      cycle={state.cycle} timezone={draft.timezone}
                      onChange={value => edit({...draft,signup_deadline:value})}/>
                    </div>
                    <p className="small">
                      Website signups are currently{" "}
                      {state.signup_open ? "open" : "closed"}. Reminders do not
                      open or close website signups or external forms.
                    </p>
                    <h3>Reminder frequency</h3>
                    <label>
                      Plan
                      <select
                        value={
                          draft.reminder_sequence.enabled
                            ? draft.reminder_sequence.mode
                            : "individual"
                        }
                        onChange={(event) =>
                          edit({
                            ...draft,
                            reminder_sequence:
                              event.target.value === "individual"
                                ? { enabled: false }
                                : {
                                    enabled: true,
                                    mode: event.target.value,
                                    count: 4,
                                    interval_hours: 48,
                                    final_hours: 3,
                                    min_gap_hours: 3,
                                  },
                          })
                        }
                      >
                        <option value="individual">
                          Individual message times
                        </option>
                        <option value="evenly">Evenly spaced reminders</option>
                        <option value="interval">
                          Every set number of hours
                        </option>
                      </select>
                    </label>
                    {draft.reminder_sequence.enabled ? (
                      <div className="reminder-fields">
                        {(
                          [
                            "count",
                            "interval_hours",
                            "final_hours",
                          ] as const
                        )
                          .filter(
                            (key) =>
                              key !== "count" ||
                              draft.reminder_sequence.mode === "evenly",
                          )
                          .filter(
                            (key) =>
                              key !== "interval_hours" ||
                              draft.reminder_sequence.mode === "interval",
                          )
                          .map((key) => (
                            <label key={key}>
                              {
                                {
                                  count: "Total reminders",
                                  interval_hours: "Hours between reminders",
                                  final_hours:
                                    "Final reminder hours before close",
                                }[key]
                              }
                              <input
                                type="number"
                                min={1}
                                max={
                                  key === "count"
                                    ? 10
                                    : 744
                                }
                                value={draft.reminder_sequence[key] ?? 1}
                                onChange={(event) =>
                                  edit({
                                    ...draft,
                                    reminder_sequence: {
                                      ...draft.reminder_sequence,
                                      [key]: Number(event.target.value),
                                    },
                                  })
                                }
                              />
                            </label>
                          ))}
                      </div>
                    ) : (
                      Object.entries(draft.messages)
                        .filter(([id]) => id !== "signup" && id !== "roster")
                        .map(([id, item]) => (
                          <details key={id}>
                            <summary>{item.label || id}</summary>
                            <TimingEditor
                              value={item.schedule}
                              onChange={(value) => {
                                const next = clone(draft);
                                next.messages[id].schedule = value;
                                edit(next);
                              }}
                            />
                          </details>
                        ))
                    )}
                    <details>
                      <summary>Advanced reminder settings</summary>
                    <label>
                      Schedule timezone
                      <input
                        value={draft.timezone}
                        onChange={(event) =>
                          edit({ ...draft, timezone: event.target.value })
                        }
                        placeholder="America/New_York"
                      />
                    </label>
                      {draft.reminder_sequence.enabled && <label>Minimum hours between reminders
                        <input type="number" min={1} max={24} value={draft.reminder_sequence.min_gap_hours ?? 3}
                          onChange={event=>edit({...draft,reminder_sequence:{...draft.reminder_sequence,min_gap_hours:Number(event.target.value)}})}/>
                      </label>}
                    </details>
                    <p className="small">
                      Saved settings repeat every month. Specific dates are
                      converted to monthly rules for future months.
                    </p>
                  </fieldset>
                </div>
              )}
              {tab === "history" && (
                <div className="card">
                  <h3>Shared delivery history</h3>
                  <p>
                    Refresh to check delivery. This page does not send messages.
                  </p>
                  {state.history?.length ? (
                    state.history.slice(0, 30).map((entry, index) => (
                      <div className="reminder-history-row" key={index}>
                        <strong>
                          {String(
                            entry.message_id ||
                              entry.message_key ||
                              entry.action ||
                              entry.status ||
                              "Reminder activity",
                          )}
                        </strong>
                        <span>
                          {String(entry.variant || entry.pool || "")}{" "}
                          {String(entry.status || "")}
                        </span>
                        <small>
                          {displayTime(
                            String(
                              entry.at ||
                                entry.sent_at ||
                                entry.updated_at ||
                                "",
                            ),
                          )}
                        </small>
                      </div>
                    ))
                  ) : (
                    <p>No recorded delivery activity for this CWL month.</p>
                  )}
                </div>
              )}
              {tab !== "history" && (tab !== "overview" || dirty) && (
                <div className={`reminder-save ${dirty ? 'has-changes' : ''}`}>
                  <span>
                    {error || (dirty
                      ? preview
                        ? "Review ready — save to apply your changes"
                        : "Unsaved changes"
                      : "All changes saved")}
                  </span>
                  <div className="reminder-control-actions" role="group" aria-label="Review and save">
                  <button
                    disabled={disabled || !dirty}
                    onClick={() =>
                      void act(async () => {
                        setPreview(
                          await api<CampaignState>(
                            base + "/preview",
                            "POST",
                            body,
                          ),
                        );
                        setNotice(
                          "Preview ready. Review the schedule below before saving.",
                        );
                      })
                    }
                  >
                    Preview schedule
                  </button>
                  <button
                    className="primary"
                    disabled={disabled || !dirty}
                    onClick={() => void act(async () => {
                      const checked = await api<CampaignState>(base + "/preview", "POST", body);
                      setPreview(checked);
                      setConfirmation({
                        text: "Save these reminder settings? They repeat monthly, and the bot will use the new times for enabled messages. Already-sent messages will not be sent again.",
                        action: () =>
                          void act(async () => {
                            const result = await api<CampaignState>(
                              base,
                              "PATCH",
                              body,
                            );
                            await load();
                            setNotice(
                              result.warning ||
                                "Saved to Manage. Signup links are unchanged; the existing bot will reconcile scheduled sends.",
                            );
                          }),
                      });
                    })}
                  >
                    Save changes
                  </button>
                  </div>
                </div>
              )}
              {tab === "schedule" || preview ? (
                <details className="reminder-disclosure reminder-schedule-panel" key={preview ? "preview" : "saved"} open={!!preview}>
                  <summary>{preview ? "Review schedule changes" : "View saved schedule"}</summary>
                  <p>
                    Times below use your browser timezone. Schedule timezone:{" "}
                    {draft.timezone}.
                  </p>
                  {(preview?.protected_sent?.length || 0) > 0 && (
                    <p className="notice">
                      Already sent messages will not be sent again.
                    </p>
                  )}
                  <div className="reminder-schedule">
                    {schedule
                      .filter((item) => item.message_id !== "roster")
                      .map((item) => (
                        <div key={item.id}>
                          <strong>
                            {draft.messages[item.message_id]?.label ||
                              item.message_id}
                          </strong>
                          <span>
                            {item.variant === "main" ? "Main" : "Lazy"}
                          </span>
                          <time>{displayTime(item.run_at)}</time>
                          <small>
                            {item.status ||
                              (state.sent_occurrences?.includes(item.id)
                                ? "Sent"
                                : state.skipped?.includes(item.id)
                                  ? "Skipped"
                                  : draft.paused
                                    ? "Paused"
                                    : item.run_at &&
                                        new Date(item.run_at) > new Date()
                                      ? "Upcoming"
                                      : "Check delivery history")}
                          </small>
                        </div>
                      ))}
                  </div>
                  {!schedule.length && <p>No enabled scheduled messages.</p>}
                </details>
              ) : null}
              <details className="reminder-disclosure reminder-context">
                <summary>About this schedule · {state.cycle}</summary>
                <p>Messages and times repeat monthly and also update Discord /manage. Existing signup links stay unchanged. Previously sent messages are not resent.</p>
              </details>
            </>
          )}
        </>
      )}
      {confirmation && (
        <ConfirmDialog
          text={confirmation.text}
          onCancel={() => setConfirmation(null)}
          onConfirm={() => {
            const action = confirmation.action;
            setConfirmation(null);
            action();
          }}
        />
      )}
    </section>
  );
}

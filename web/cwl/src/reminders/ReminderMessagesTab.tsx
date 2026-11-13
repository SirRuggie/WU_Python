import ChannelCombobox from "../ChannelCombobox";
import DiscordPreview, { type PreviewPart } from "../DiscordMessagePreview";
import SearchPicker from "../SearchPicker";
import SectionTabs from "../SectionTabs";
import { roleOption } from "../RolePicker";
import type { AnnouncementChannel } from "../announcements";
import type { Campaign, Variant } from "../reminderCampaign";
import type { Pool } from "../api";
import MessagePreview from "./MessagePreview";
import { shortReminderTime } from "./SignupReminderOverview";
import { clone } from "./reminderWorkspaceHelpers";

type Lookup<T> = {
  items: T[];
  error: string;
  loading: boolean;
  retry: () => void;
};

export default function ReminderMessagesTab({
  draft,
  messageId,
  setMessageId,
  pool,
  setPool,
  disabled,
  channels,
  roles,
  channelLookup,
  roleLookup,
  roleText,
  setRoleText,
  edit,
  changeVariant,
  previewDeadline,
}: {
  draft: Campaign;
  messageId: string;
  setMessageId: (id: string) => void;
  pool: Pool;
  setPool: (pool: Pool) => void;
  disabled: boolean;
  channels: AnnouncementChannel[];
  roles: { id: string; name: string }[];
  channelLookup: Lookup<AnnouncementChannel>;
  roleLookup: Lookup<{ id: string; name: string }>;
  roleText: string;
  setRoleText: (text: string) => void;
  edit: (next: Campaign) => void;
  changeVariant: (change: Partial<Variant>) => void;
  previewDeadline: string | undefined;
}) {
  const channelError = channelLookup.error;
  const selected = draft.messages[messageId];
  const variant = selected?.variants[pool];
  return (
    <>
      <div className="reminder-editor-intro">
        <SectionTabs
          className="tabs workflow-tabs section-tabs--flow"
          label="Message audience"
          items={(["main", "lazy"] as const).map((value) => {
            return {
              id: value,
              label: <>{value === "main" ? "Main" : "Lazy"}</>,
            };
          })}
          value={pool}
          onChange={(value) => {
            setPool(value);
          }}
          revealSelection
        />
      </div>
      <div className="reminder-fields">
        <SearchPicker
          label="Message to edit"
          value={messageId}
          options={Object.entries(draft.messages)
            .filter(([id]) => id !== "roster")
            .map(([id, item]) => ({
              value: id,
              label: item.label || id,
            }))}
          placeholder="Select a message"
          searchPlaceholder="Search messages"
          emptyText="No messages match."
          onChange={setMessageId}
        />
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
                    next.messages[messageId].enabled = event.target.checked;
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
              {(channelError || roleLookup.error) && (
                <p role="alert">
                  Delivery settings need attention. Open Delivery settings below
                  to retry the failed lookup.
                </p>
              )}
              <details className="reminder-disclosure">
                <summary>
                  Delivery settings · {variant.role_ids.length}{" "}
                  {variant.role_ids.length === 1 ? "role" : "roles"} to notify
                </summary>
                <ChannelCombobox
                  label="Destination channel"
                  channels={channels}
                  value={variant.destination_channel_id}
                  disabled={disabled || channelLookup.loading || !!channelError}
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
                    <button type="button" onClick={channelLookup.retry}>
                      Retry channels
                    </button>
                  </div>
                )}
                <SearchPicker
                  label="Add a role"
                  value=""
                  options={roles.map((role) => ({
                    ...roleOption(role),
                    disabledNote: variant.role_ids.includes(role.id)
                      ? "Already added"
                      : undefined,
                  }))}
                  disabled={roleLookup.loading || !!roleLookup.error}
                  placeholder="Add a role"
                  searchPlaceholder="Search server roles"
                  emptyText="No roles match."
                  onChange={(id) => {
                    if (!id) return;
                    const next = [...new Set([...variant.role_ids, id])];
                    setRoleText(next.join(", "));
                    changeVariant({ role_ids: next });
                  }}
                />
                {roleLookup.loading && <p role="status">Loading roles…</p>}
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
                    <p className="small">No roles selected for notification.</p>
                  )}
                </div>
                <details>
                  <summary>Role IDs</summary>
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
                      These roles are notified when this message is sent.
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
                  Discord formatting is supported. Use {"{signup_deadline}"} for
                  the shared closing date.
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
                      changeVariant({
                        media_url: event.target.value,
                      })
                    }
                  />
                </label>
              </details>
            </fieldset>
          </div>
          <MessagePreview key={messageId + pool}>
            <DiscordPreview
              parts={[
                {
                  type: "container",
                  children: [
                    { type: "text", text: "## " + variant.title },
                    {
                      type: "text",
                      text: variant.body.replaceAll(
                        "{signup_deadline}",
                        shortReminderTime(previewDeadline),
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
            />
          </MessagePreview>
        </div>
      )}
    </>
  );
}

import ChannelCombobox from "../ChannelCombobox";
import LoadError from "../LoadError";
import DiscordPreview, { type PreviewPart } from "../DiscordMessagePreview";
import SearchPicker from "../SearchPicker";
import SectionTabs from "../SectionTabs";
import { roleOption } from "../RolePicker";
import type { AnnouncementChannel } from "../announcements";
import type { Campaign, Variant } from "../reminderCampaign";
import type { Pool } from "../api";
import MessagePreview from "./MessagePreview";
import { shortReminderTime } from "./reminderFormat";
import { clone } from "./reminderWorkspaceHelpers";
import { variantErrors, type ReminderLookup } from "./reminderErrors";

type Lookup<T extends { id: string }> = ReminderLookup<T> & {
  retry: () => void;
};

export default function ReminderMessageEditor({
  draft,
  messageId,
  pool,
  setPool,
  showPoolSwitch,
  disabled,
  compact,
  channelLookup,
  roleLookup,
  edit,
  previewDeadline,
}: {
  draft: Campaign;
  messageId: string;
  pool: Pool;
  setPool: (pool: Pool) => void;
  showPoolSwitch: boolean;
  disabled: boolean;
  compact: boolean;
  channelLookup: Lookup<AnnouncementChannel>;
  roleLookup: Lookup<{ id: string; name: string }>;
  edit: (next: Campaign) => void;
  previewDeadline?: string;
}) {
  const message = draft.messages[messageId];
  const variant = message?.variants[pool];
  if (!message || !variant) return null;
  const errors = variantErrors(draft, messageId, pool, {
    channels: channelLookup,
    roles: roleLookup,
  });
  const errorFor = (...codes: string[]) => {
    const matching = errors.filter((error) => codes.includes(error.code));
    return matching.length ? (
      <small className="reminder-field-error">
        {matching.map((error) => error.label).join(" · ")}
      </small>
    ) : null;
  };
  const changeVariant = (patch: Partial<Variant>) => {
    const next = clone(draft);
    Object.assign(next.messages[messageId].variants[pool], patch);
    edit(next);
  };
  return (
    <section className="reminder-editor" aria-label="Message editor">
      {showPoolSwitch && (
        <SectionTabs
          mode="segmented"
          label="Version to edit"
          value={pool}
          items={[
            { id: "main", label: "Main CWL" },
            { id: "lazy", label: "Lazy CWL" },
          ]}
          onChange={setPool}
          disabled={disabled}
        />
      )}
      <h2>
        {message.label || "Message"} ·{" "}
        {pool === "main" ? "Main CWL" : "Lazy CWL"}
      </h2>
      <div className="reminder-editor-content">
        <fieldset disabled={disabled}>
          <label className="check-label">
            <input
              type="checkbox"
              checked={message.enabled}
              onChange={(event) => {
                const next = clone(draft);
                next.messages[messageId].enabled = event.target.checked;
                edit(next);
              }}
            />
            Send this message (Main and Lazy)
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={variant.enabled !== false}
              onChange={(event) =>
                changeVariant({ enabled: event.target.checked })
              }
            />
            Send {pool === "main" ? "Main" : "Lazy"} version
          </label>
          <ChannelCombobox
            label="Destination channel"
            channels={channelLookup.items}
            value={variant.destination_channel_id}
            disabled={
              disabled || channelLookup.loading || !!channelLookup.error
            }
            onChange={(destination_channel_id) =>
              changeVariant({ destination_channel_id })
            }
          />
          {errorFor("no_channel", "unknown_channel")}
          {(channelLookup.loading || channelLookup.error) && (
            <p className="reminder-names-unavailable">Names unavailable</p>
          )}
          <LoadError
            message={channelLookup.error}
            onRetry={channelLookup.retry}
          />
          <SearchPicker
            label="Add a role"
            value=""
            options={roleLookup.items.map((role) => ({
              ...roleOption(role),
              disabledNote: variant.role_ids.includes(role.id)
                ? "Already added"
                : undefined,
            }))}
            disabled={disabled || roleLookup.loading || !!roleLookup.error}
            placeholder="Add a role"
            searchPlaceholder="Search server roles"
            emptyText="No roles match."
            onChange={(id) => {
              if (id)
                changeVariant({
                  role_ids: [...new Set([...variant.role_ids, id])],
                });
            }}
          />
          {(roleLookup.loading || roleLookup.error) && (
            <p className="reminder-names-unavailable">Names unavailable</p>
          )}
          <LoadError message={roleLookup.error} onRetry={roleLookup.retry} />
          <div
            className="reminder-selected-roles"
            role="group"
            aria-label="Roles to notify"
          >
            {variant.role_ids.length ? (
              variant.role_ids.map((id) => {
                const name = roleLookup.items.find(
                  (role) => role.id === id,
                )?.name;
                return (
                  <button
                    type="button"
                    key={id}
                    disabled={disabled}
                    aria-label={name ? `Remove ${name}` : "Remove unknown role"}
                    onClick={() =>
                      changeVariant({
                        role_ids: variant.role_ids.filter(
                          (value) => value !== id,
                        ),
                      })
                    }
                  >
                    {name || "Unknown role"} ×
                  </button>
                );
              })
            ) : (
              <p className="small">No roles selected for notification.</p>
            )}
          </div>
          {errorFor("unknown_role")}
          <label>
            Title
            <input
              maxLength={4000}
              value={variant.title}
              onChange={(event) => changeVariant({ title: event.target.value })}
            />
            {errorFor("empty_title")}
          </label>
          <label>
            Message
            <textarea
              rows={8}
              maxLength={4000}
              value={variant.body}
              onChange={(event) => changeVariant({ body: event.target.value })}
            />
            {errorFor("empty_body")}
            <small>
              Discord formatting is supported. Use {"{signup_deadline}"} for the
              shared closing date.
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
        <MessagePreview key={messageId + pool} defaultOpen={!compact}>
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
    </section>
  );
}

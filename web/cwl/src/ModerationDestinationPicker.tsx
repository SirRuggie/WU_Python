import ChannelCombobox from "./ChannelCombobox";
import type { AnnouncementChannel } from "./announcements";
import type { Destination, RouteTarget } from "./moderationSettingsModel";

type Props = {
  label: string;
  value: RouteTarget;
  channels: Destination[];
  disabled: boolean;
  onChange: (value: RouteTarget) => void;
  onResolve: (channelId: string) => void;
};

export default function ModerationDestinationPicker({
  label,
  value,
  channels,
  disabled,
  onChange,
  onResolve,
}: Props) {
  const selected = channels.find((item) => item.id === value.channel_id);
  const options: AnnouncementChannel[] = channels
    .filter((item) => item.can_post)
    .map((item) => ({
      id: item.id,
      name: item.name,
      type: item.type === "forum" ? 15 : item.type === "forum_post" ? 11 : 0,
    }));
  const tags = selected?.type === "forum" ? selected.available_tags : [];
  const selectableTags = tags.filter(
    (tag) => !tag.moderated || selected?.can_manage_threads,
  );

  return (
    <div className="moderation-destination">
      <ChannelCombobox
        label={label}
        channels={options}
        value={value.channel_id || ""}
        disabled={disabled}
        onResolve={onResolve}
        onChange={(channelId) =>
          onChange({
            channel_id: channelId || null,
            forum_tag_id:
              channelId === value.channel_id ? value.forum_tag_id : null,
          })
        }
      />
      {selected?.type === "forum_post" && (
        <p className="moderation-destination-help">
          Notices will be replies in this existing forum post.
        </p>
      )}
      {selected?.type === "forum" && (
        <label className="moderation-forum-tag">
          Forum tag {selected.requires_tag ? "(required)" : "(optional)"}
          <select
            value={value.forum_tag_id || ""}
            disabled={disabled || selectableTags.length === 0}
            onChange={(event) =>
              onChange({
                ...value,
                forum_tag_id: event.target.value || null,
              })
            }
          >
            <option value="">
              {selected.requires_tag ? "Choose a forum tag" : "No forum tag"}
            </option>
            {selectableTags.map((tag) => (
              <option key={tag.id} value={tag.id}>
                {tag.name}
              </option>
            ))}
          </select>
          {tags.length === 0 && selected.requires_tag && (
            <small>This forum requires a tag, but none are available.</small>
          )}
          {tags.some((tag) => tag.moderated) &&
            !selected.can_manage_threads && (
              <small>Moderated tags require Manage Threads permission.</small>
            )}
        </label>
      )}
    </div>
  );
}

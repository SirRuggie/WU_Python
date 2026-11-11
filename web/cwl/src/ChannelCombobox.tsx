import type { AnnouncementChannel } from "./announcements";
import { filterChannels } from "./channelSearch";
import SearchPicker, { type PickerOption } from "./SearchPicker";

type Props = {
  label: string;
  channels: AnnouncementChannel[];
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onResolve?: (value: string) => void;
  /** Kept for existing call sites; raw IDs are never shown. */
  nameOnly?: boolean;
};
const visibleLimit = 30;
const CATEGORY = 4;
const FORUM_POST = 11;
const FORUM = 15;
const LOOKUP_ID = /^[0-9]{15,22}$/;
// Prefix so a lookup row never equals the saved value (a saved but hidden post).
const LOOKUP = "lookup:";

function typeWord(type: number) {
  if (type === FORUM_POST) return "Forum post";
  if (type === FORUM) return "Forum";
  return undefined;
}

function channelOption(channel: AnnouncementChannel): PickerOption {
  return {
    value: channel.id,
    label: channel.type === CATEGORY ? channel.name : `#${channel.name}`,
    detail: typeWord(channel.type),
  };
}

/** Channel field with name search; a pasted ID finds the channel too. */
export default function ChannelCombobox({
  label,
  channels,
  value,
  disabled,
  onChange,
  onResolve,
}: Props) {
  const options = channels.map(channelOption);

  // An ID that is not in the list can only be looked up, never selected.
  const isLookup = (id: string) =>
    !!onResolve &&
    LOOKUP_ID.test(id) &&
    !channels.some((channel) => channel.id === id);

  function search(query: string): PickerOption[] {
    const lookupId = query.trim();
    if (isLookup(lookupId))
      return [
        { value: LOOKUP + lookupId, label: "Look up channel or forum post ID" },
      ];
    return filterChannels(channels, query).map(channelOption);
  }

  function choose(id: string) {
    if (id.startsWith(LOOKUP)) onResolve?.(id.slice(LOOKUP.length));
    else onChange(id);
  }

  return (
    <div className="channel-combobox">
      <SearchPicker
        label={label}
        value={value}
        options={options}
        onChange={choose}
        placeholder={
          onResolve ? "Select a channel or forum post" : "Select a channel"
        }
        searchPlaceholder={
          onResolve ? "Search channels and forum posts" : "Search channels"
        }
        emptyText="No channels match."
        disabled={disabled}
        clearable
        fallback={{ value, label: "Selected channel unavailable" }}
        search={search}
        limit={visibleLimit}
      />
    </div>
  );
}

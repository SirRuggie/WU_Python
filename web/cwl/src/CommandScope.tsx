import ChannelCombobox from "./ChannelCombobox";
import RoleSelect from "./RoleSelect";
import type { AnnouncementChannel } from "./announcements";
import type { RoleChoice } from "./CommandExtras";
import type { Command } from "./CommandBuilder";

export default function CommandScope({
  draft,
  channels,
  roles,
  onChange,
  disabled,
}: {
  draft: Command;
  channels: AnnouncementChannel[];
  roles: RoleChoice[];
  onChange: (
    key: "allowed_channel_ids" | "allowed_role_ids",
    values: string[],
  ) => void;
  disabled: boolean;
}) {
  const selectedChannels = draft.allowed_channel_ids ?? [],
    selectedRoles = draft.allowed_role_ids ?? [];
  return (
    <div className="command-scope">
      <p>Leave these lists empty for every channel and everyone.</p>
      <ChannelCombobox
        label="Only in these channels"
        channels={channels.filter((c) => !selectedChannels.includes(c.id))}
        value=""
        disabled={disabled}
        onChange={(id) => {
          if (id) onChange("allowed_channel_ids", [...selectedChannels, id]);
        }}
      />
      {selectedChannels.map((id) => (
        <button
          type="button"
          key={id}
          disabled={disabled}
          onClick={() =>
            onChange(
              "allowed_channel_ids",
              selectedChannels.filter((item) => item !== id),
            )
          }
        >
          Remove #
          {channels.find((c) => c.id === id)?.name ?? "unavailable channel"}
        </button>
      ))}
      <RoleSelect
        label="Only for these roles"
        roles={roles.filter((r) => !selectedRoles.includes(r.id))}
        value=""
        disabled={disabled}
        onChange={(id) => {
          if (id) onChange("allowed_role_ids", [...selectedRoles, id]);
        }}
      />
      {selectedRoles.map((id) => (
        <button
          type="button"
          key={id}
          disabled={disabled}
          onClick={() =>
            onChange(
              "allowed_role_ids",
              selectedRoles.filter((item) => item !== id),
            )
          }
        >
          Remove {roles.find((r) => r.id === id)?.name ?? "unavailable role"}
        </button>
      ))}
    </div>
  );
}

import RolePicker, { type RoleChoice } from "./RolePicker";
import SearchPicker from "./SearchPicker";
import {
  maxIgnoreIds,
  type Destination,
  type LinkIgnores,
} from "./moderationSettingsModel";

type Props = {
  ignores: LinkIgnores;
  channels: Destination[];
  roles?: RoleChoice[] | null;
  rolesAvailable: boolean;
  disabled: boolean;
  onChange: (value: LinkIgnores) => void;
};

function Chips({
  ids,
  name,
  disabled,
  onRemove,
}: {
  ids: string[];
  name: (id: string) => string;
  disabled: boolean;
  onRemove: (id: string) => void;
}) {
  if (ids.length === 0) return <small>None</small>;
  return (
    <ul className="moderation-ignore-chips">
      {ids.map((id) => (
        <li key={id}>
          <span>{name(id)}</span>
          <button
            type="button"
            disabled={disabled}
            aria-label={`Remove ${name(id)}`}
            onClick={() => onRemove(id)}
          >
            ×
          </button>
        </li>
      ))}
    </ul>
  );
}

export default function ModerationIgnoreLists({
  ignores,
  channels,
  roles,
  rolesAvailable,
  disabled,
  onChange,
}: Props) {
  const channelName = (id: string) => {
    const channel = channels.find((item) => item.id === id);
    return channel ? `#${channel.name}` : "Deleted channel";
  };
  const available = channels.filter(
    (item) => !ignores.channel_ids.includes(item.id),
  );
  const roleName = (id: string) => {
    if (!rolesAvailable) return "Unknown role";
    const role = roles?.find((item) => item.id === id);
    return role ? `@${role.name}` : "Deleted role";
  };

  return (
    <div className="moderation-ignore-lists">
      <div className="moderation-ignore-group">
        <SearchPicker
          label="Ignored channels"
          value=""
          options={available.map((item) => ({
            value: item.id,
            label: `#${item.name}`,
            detail:
              item.type === "forum"
                ? "Forum"
                : item.type === "forum_post"
                  ? "Forum post"
                  : undefined,
          }))}
          disabled={
            disabled ||
            available.length === 0 ||
            ignores.channel_ids.length >= maxIgnoreIds
          }
          placeholder="Add a channel"
          searchPlaceholder="Search channels"
          emptyText="No channels match."
          onChange={(id) => {
            if (id)
              onChange({
                ...ignores,
                channel_ids: [...ignores.channel_ids, id],
              });
          }}
        />
        <Chips
          ids={ignores.channel_ids}
          name={channelName}
          disabled={disabled}
          onRemove={(id) =>
            onChange({
              ...ignores,
              channel_ids: ignores.channel_ids.filter((item) => item !== id),
            })
          }
        />
      </div>
      <div className="moderation-ignore-group">
        {rolesAvailable ? (
          <RolePicker
            roles={roles || []}
            selected={ignores.role_ids}
            disabled={disabled || ignores.role_ids.length >= maxIgnoreIds}
            label="Ignored roles"
            onChoose={(role) =>
              onChange({ ...ignores, role_ids: [...ignores.role_ids, role.id] })
            }
          />
        ) : (
          <>
            <span>Ignored roles</span>
            <small>Roles unavailable.</small>
          </>
        )}
        <Chips
          ids={ignores.role_ids}
          name={roleName}
          disabled={disabled}
          onRemove={(id) =>
            onChange({
              ...ignores,
              role_ids: ignores.role_ids.filter((item) => item !== id),
            })
          }
        />
      </div>
    </div>
  );
}

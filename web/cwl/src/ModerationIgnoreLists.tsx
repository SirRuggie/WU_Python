import { useState } from "react";
import {
  maxIgnoreIds,
  normalizeRoleId,
  type Destination,
  type LinkIgnores,
} from "./moderationSettingsModel";

type Props = {
  ignores: LinkIgnores;
  channels: Destination[];
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
  disabled,
  onChange,
}: Props) {
  const [roleText, setRoleText] = useState("");
  const [roleError, setRoleError] = useState("");
  const channelName = (id: string) => {
    const channel = channels.find((item) => item.id === id);
    return channel ? `#${channel.name}` : `Channel ${id}`;
  };
  const available = channels.filter(
    (item) => !ignores.channel_ids.includes(item.id),
  );
  const addRole = () => {
    const id = normalizeRoleId(roleText);
    if (!id) {
      setRoleError("Enter a role ID with 17 to 20 digits.");
      return;
    }
    if (ignores.role_ids.includes(id)) {
      setRoleError("That role is already ignored.");
      return;
    }
    if (ignores.role_ids.length >= maxIgnoreIds) {
      setRoleError(`At most ${maxIgnoreIds} roles.`);
      return;
    }
    setRoleError("");
    setRoleText("");
    onChange({ ...ignores, role_ids: [...ignores.role_ids, id] });
  };

  return (
    <div className="moderation-ignore-lists">
      <div className="moderation-ignore-group">
        <label>
          Ignored channels
          <select
            value=""
            disabled={
              disabled ||
              available.length === 0 ||
              ignores.channel_ids.length >= maxIgnoreIds
            }
            onChange={(event) => {
              if (event.target.value)
                onChange({
                  ...ignores,
                  channel_ids: [...ignores.channel_ids, event.target.value],
                });
            }}
          >
            <option value="">Select a channel</option>
            {available.map((item) => (
              <option key={item.id} value={item.id}>
                #{item.name}
              </option>
            ))}
          </select>
        </label>
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
        <label>
          Ignored roles
          <span className="moderation-ignore-add">
            <input
              value={roleText}
              inputMode="numeric"
              placeholder="Role ID"
              disabled={disabled}
              onChange={(event) => {
                setRoleText(event.target.value);
                setRoleError("");
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  addRole();
                }
              }}
            />
            <button type="button" disabled={disabled} onClick={addRole}>
              Add
            </button>
          </span>
        </label>
        {roleError && <small role="alert">{roleError}</small>}
        <Chips
          ids={ignores.role_ids}
          name={(id) => `Role ${id}`}
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

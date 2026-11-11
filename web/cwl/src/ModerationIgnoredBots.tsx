import SearchPicker from "./SearchPicker";
import { maxIgnoredBots, type BotActor } from "./moderationSettingsModel";

function lastSeen(value: string | null) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime())
    ? `Last seen ${date.toLocaleDateString()}`
    : undefined;
}

type Props = {
  ids: string[] | undefined;
  actors: BotActor[];
  disabled: boolean;
  onChange: (ids: string[]) => void;
};

export default function ModerationIgnoredBots({
  ids,
  actors,
  disabled,
  onChange,
}: Props) {
  if (!ids) {
    return (
      <div className="moderation-ignored-bots">
        <h3>Ignored bots</h3>
        <small>Bot list unavailable.</small>
      </div>
    );
  }
  const name = (id: string) => {
    const actor = actors.find((item) => item.id === id);
    return actor ? `@${actor.name}` : "Unknown bot";
  };
  const available = actors.filter((item) => !ids.includes(item.id));
  return (
    <div className="moderation-ignored-bots">
      <h3>Ignored bots</h3>
      <p>Changes made by these bots are not logged.</p>
      <div className="moderation-ignore-group">
        <SearchPicker
          label="Add an ignored bot"
          value=""
          options={available.map((item) => ({
            value: item.id,
            label: `@${item.name}`,
            detail: lastSeen(item.last_seen),
          }))}
          disabled={
            disabled || available.length === 0 || ids.length >= maxIgnoredBots
          }
          placeholder="Add a bot"
          searchPlaceholder="Search bots"
          emptyText="No bots match."
          onChange={(id) => {
            if (id) onChange([...ids, id]);
          }}
        />
        {ids.length === 0 ? (
          <small>None</small>
        ) : (
          <ul className="moderation-ignore-chips">
            {ids.map((id) => (
              <li key={id}>
                <span>{name(id)}</span>
                <button
                  type="button"
                  disabled={disabled}
                  aria-label={`Remove ${name(id)}`}
                  onClick={() => onChange(ids.filter((item) => item !== id))}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

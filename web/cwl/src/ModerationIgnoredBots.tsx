import { maxIgnoredBots, type BotActor } from "./moderationSettingsModel";

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
        <label>
          Add an ignored bot
          <select
            value=""
            disabled={
              disabled || available.length === 0 || ids.length >= maxIgnoredBots
            }
            onChange={(event) => {
              if (event.target.value) onChange([...ids, event.target.value]);
            }}
          >
            <option value="">Select a bot</option>
            {available.map((item) => (
              <option key={item.id} value={item.id}>
                @{item.name}
              </option>
            ))}
          </select>
        </label>
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

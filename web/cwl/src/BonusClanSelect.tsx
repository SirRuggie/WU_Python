import type { Pool } from "./api";
import SearchPicker from "./SearchPicker";
import { bonusClanCardText, type BonusStatus } from "./bonusStatus";
import "./BonusClanSelect.css";

type Props = {
  clans: { tag: string; name: string }[];
  /** The open clan, or "all" for the season overview. */
  selected: string;
  pool: Pool;
  status: BonusStatus | null;
  /** True when a clan opens its bonus steps; false when it only filters Results. */
  opensSteps: boolean;
  disabled: boolean;
  onChange: (tag: string) => void;
};

const CLAN_PICKER_LIMIT = 20;

/** The one Hosting clan control: All clans first, then each clan with its bonus state. */
export default function BonusClanSelect({
  clans,
  selected,
  pool,
  status,
  opensSteps,
  disabled,
  onChange,
}: Props) {
  const stateText = (tag: string) => {
    const state = status?.pools[pool].find((item) => item.tag === tag);
    return state ? bonusClanCardText(state) : "";
  };
  const options = [
    { value: "all", label: "All clans" },
    ...clans.map((clan) => {
      const text = stateText(clan.tag);
      return {
        value: clan.tag,
        label: text ? `${clan.name} · ${text}` : clan.name,
      };
    }),
  ];
  // A selected clan's state is already in its option text.
  const line =
    selected === "all" && opensSteps
      ? "Select a clan to open its bonus steps."
      : "";
  return (
    <div className="bonus-clan-select">
      {clans.length > CLAN_PICKER_LIMIT ? (
        <SearchPicker
          label="Hosting clan"
          value={selected}
          options={options}
          disabled={disabled}
          placeholder="All clans"
          searchPlaceholder="Search clans"
          emptyText="No clans match."
          onChange={onChange}
        />
      ) : (
        <label>
          Hosting clan
          <select
            name="clan"
            autoComplete="off"
            value={selected}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
          >
            {options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      )}
      {line && <p className="bonus-clan-line">{line}</p>}
    </div>
  );
}

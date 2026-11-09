import { useEffect, useMemo, useRef, useState } from "react";
import ActionPanel from "./ActionPanel";
import RosterFilterOptions from "./RosterFilterOptions";
import StrikeMemberSelect, { strikeMemberOptions } from "./StrikeMemberSelect";
import { api } from "./api";
import { compactWeight, parseWeights, weightsText } from "./replacementView";
import { memberName } from "./strikeActivityFilters";
import type { ActivityAccount } from "./strikeActivityView";
import type { Priority } from "./replacementTypes";

export type SlotSearch = {
  slotWeights: number[];
  slotClans: string[];
  slotMember: string;
};
type Candidate = {
  player_tag: string;
  player_name: string;
  clan_name?: string | null;
  weight?: number | null;
  weight_difference?: number | null;
  town_hall?: number | null;
  priority?: Priority | null;
  active_strikes: number;
  discord_id?: string | null;
  discord_name?: string | null;
};
type Slot = { weight: number; weight_label: string; candidates: Candidate[] };
const key = (search: SlotSearch) =>
  JSON.stringify([search.slotWeights, search.slotClans, search.slotMember]);
const priorityLabel = (value?: Priority | null) =>
  value === "replace_first" ? "Chopping Block" : value === "high" ? "High" : "";

/** Closest slots for each recruit weight. A search runs only from Find or a restored link. */
export default function FindSlots({
  clans,
  accounts,
  search,
  disabled = false,
  onSearch,
  onChoose,
}: {
  clans: { tag: string; name: string; is_fwa?: boolean }[];
  accounts: ActivityAccount[];
  search: SlotSearch;
  disabled?: boolean;
  onSearch: (next: SlotSearch) => void;
  onChoose: (row: ActivityAccount) => void;
}) {
  const fwa = useMemo(() => clans.filter((clan) => clan.is_fwa), [clans]);
  const restored: SlotSearch = {
    slotWeights: search.slotWeights,
    slotClans: search.slotClans.filter((tag) =>
      fwa.some((clan) => clan.tag === tag),
    ),
    slotMember: search.slotMember,
  };
  const restoredKey = key(restored);
  const [text, setText] = useState(weightsText(restored.slotWeights)),
    [picked, setPicked] = useState(restored.slotClans),
    [member, setMember] = useState(restored.slotMember),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [slots, setSlots] = useState<Slot[] | null>(null),
    [panel, setPanel] = useState<{
      kind: "clans" | "member";
      trigger: HTMLElement;
    } | null>(null),
    [clanSearch, setClanSearch] = useState("");
  const turn = useRef(0),
    ran = useRef(""),
    callbacks = useRef({ onSearch });
  callbacks.current = { onSearch };
  const members = useMemo(() => strikeMemberOptions(accounts), [accounts]);
  useEffect(
    () => () => {
      turn.current++;
    },
    [],
  );
  async function run(next: SlotSearch) {
    const id = ++turn.current;
    ran.current = key(next);
    setBusy(true);
    setError("");
    try {
      const query = new URLSearchParams();
      next.slotWeights.forEach((weight) =>
        query.append("weight", String(weight)),
      );
      next.slotClans.forEach((tag) => query.append("clan", tag));
      if (next.slotMember) query.set("member", next.slotMember);
      const data = await api<{ slots: Slot[] }>(
        `/strikes/replacements?${query}`,
      );
      if (!Array.isArray(data.slots))
        throw new Error("Slot results are incomplete. Try again.");
      if (id === turn.current) setSlots(data.slots);
    } catch (cause) {
      if (id === turn.current) {
        setSlots(null);
        setError(
          cause instanceof Error ? cause.message : "Slots are unavailable.",
        );
      }
    } finally {
      if (id === turn.current) setBusy(false);
    }
  }
  // The link or Back/Forward is an earlier explicit search: restore it and run it once.
  useEffect(() => {
    setText(weightsText(restored.slotWeights));
    setPicked(restored.slotClans);
    setMember(restored.slotMember);
    if (!restored.slotWeights.length) {
      turn.current++;
      ran.current = "";
      setSlots(null);
      setBusy(false);
      setError("");
      return;
    }
    if (ran.current !== restoredKey) void run(restored);
    // restoredKey stands for the whole restored search.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restoredKey]);
  function find() {
    const parsed = parseWeights(text);
    if (parsed.error) {
      setError(parsed.error);
      return;
    }
    const next: SlotSearch = {
      slotWeights: parsed.weights,
      slotClans: picked,
      slotMember: member,
    };
    void run(next);
    callbacks.current.onSearch(next);
  }
  const clanLabel =
    picked.length === 0
      ? "All FWA clans"
      : picked.length === 1
        ? fwa.find((clan) => clan.tag === picked[0])?.name || "1 clan"
        : `${picked.length} clans`;
  const name = members.find((option) => option.id === member)?.name;
  return (
    <section className="strike-find-slots" aria-label="Find slots">
      <h2 className="sr-only">Find slots</h2>
      <label>
        Weights
        <input
          inputMode="decimal"
          value={text}
          maxLength={80}
          disabled={disabled}
          placeholder="143, 173, 150"
          aria-invalid={!!error || undefined}
          onChange={(event) => {
            setText(event.target.value);
            setError("");
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") find();
          }}
        />
      </label>
      <div className="strike-find-slots-row">
        <button
          type="button"
          disabled={disabled}
          aria-label={`Clans: ${clanLabel}`}
          onClick={(event) =>
            setPanel({ kind: "clans", trigger: event.currentTarget })
          }
        >
          <span>{clanLabel}</span>
        </button>
        <button
          type="button"
          disabled={disabled}
          aria-label={`Member: ${name ? `@${name}` : member ? "selected" : "any"}`}
          onClick={(event) =>
            setPanel({ kind: "member", trigger: event.currentTarget })
          }
        >
          <span>
            {member ? (name ? `@${name}` : "Selected member") : "Any member"}
          </span>
        </button>
        <button
          type="button"
          className="primary"
          aria-busy={busy || undefined}
          disabled={disabled || busy}
          onClick={find}
        >
          {busy ? "Finding…" : "Find slots"}
        </button>
      </div>
      {error && <p role="alert">{error}</p>}
      {slots?.map((slot) => (
        <section key={slot.weight} className="strike-slot-group">
          <h3>{slot.weight_label || compactWeight(slot.weight)}</h3>
          {slot.candidates.length ? (
            <ol>
              {slot.candidates.map((item) => {
                const row = accounts.find(
                  (account) => account.player_tag === item.player_tag,
                );
                const who = memberName(item);
                const priority = priorityLabel(item.priority);
                return (
                  <li key={item.player_tag}>
                    <button
                      type="button"
                      disabled={!row || disabled}
                      onClick={() => row && onChoose(row)}
                    >
                      <strong>{item.player_name}</strong>
                      <span>
                        {[
                          item.town_hall ? `TH${item.town_hall}` : null,
                          item.clan_name,
                          who ? `@${who}` : null,
                          item.weight ? compactWeight(item.weight) : null,
                          item.weight_difference != null
                            ? `Gap ${compactWeight(item.weight_difference)}`
                            : null,
                          priority || null,
                          `${item.active_strikes} ${item.active_strikes === 1 ? "strike" : "strikes"}`,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p>No slot in these clans.</p>
          )}
        </section>
      ))}
      {panel?.kind === "clans" && (
        <ActionPanel
          title="Select clans"
          trigger={panel.trigger}
          onClose={() => setPanel(null)}
          expandOnSearchFocus
        >
          <label>
            Find clan
            <input
              type="search"
              value={clanSearch}
              onChange={(event) => setClanSearch(event.target.value)}
            />
          </label>
          <RosterFilterOptions
            title="FWA clans"
            selected={picked}
            onChange={setPicked}
            options={fwa
              .filter((clan) =>
                `${clan.name} ${clan.tag}`
                  .toLocaleLowerCase()
                  .includes(clanSearch.toLocaleLowerCase()),
              )
              .map((clan) => ({
                value: clan.tag,
                label: clan.name,
                count: accounts.filter(
                  (row) =>
                    (row.left_clan
                      ? row.last_clan_tag
                      : row.current_clan_tag) === clan.tag,
                ).length,
              }))}
          />
        </ActionPanel>
      )}
      {panel?.kind === "member" && (
        <ActionPanel
          title="Select member"
          trigger={panel.trigger}
          onClose={() => setPanel(null)}
          expandOnSearchFocus
        >
          <StrikeMemberSelect
            options={members}
            value={member}
            onChange={(id) => {
              setMember(id);
              if (id) setPanel(null);
            }}
          />
        </ActionPanel>
      )}
    </section>
  );
}

import { searchInputProps } from "./inputProps";
import EmptyState from "./EmptyState";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import RosterFilterOptions from "./RosterFilterOptions";
import StrikeRecruitSelect from "./StrikeRecruitSelect";
import SlotResults, {
  checkedSlotResponse,
  type SlotResponse,
} from "./SlotResults";
import LoadError from "./LoadError";
import { api, isExpectedCancel } from "./api";
import { compactWeight, parseWeights, weightsText } from "./replacementView";
import type { ActivityAccount } from "./strikeActivityView";
import {
  normalizedSlotSearch,
  slotSearchKey,
  slotGroupKeys,
  slotVisibleCount,
  type SlotSearch,
} from "./slotSearchState";
export type { SlotSearch } from "./slotSearchState";

/** Routine search controls stay on the page; every request is read-only and last-wins. */
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
  const id = useId(),
    errorId = `${id}-weights-error`,
    hintId = `${id}-weights-hint`;
  const initial = normalizedSlotSearch(search);
  const [draft, setDraft] = useState(initial),
    [text, setText] = useState(weightsText(initial.slotWeights));
  const [inputError, setInputError] = useState(""),
    [requestError, setRequestError] = useState("");
  const [busy, setBusy] = useState(false),
    [stale, setStale] = useState(false);
  const [data, setData] = useState<SlotResponse | null>(null),
    [clanQuery, setClanQuery] = useState("");
  const invalid = useRef(false);
  const draftRef = useRef(draft),
    typed = useRef(initial.slotWeights.length > 0);
  const turn = useRef(0),
    timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const controller = useRef<AbortController | null>(null),
    published = useRef<string | null>(null);
  const callbacks = useRef({ onSearch });
  callbacks.current = { onSearch };
  const fwa = useMemo(() => clans.filter((clan) => clan.is_fwa), [clans]);
  function cancel() {
    turn.current++;
    controller.current?.abort();
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  }
  async function run(next: SlotSearch) {
    if (disabled || invalid.current) {
      cancel();
      setBusy(false);
      return;
    }
    cancel();
    const current = turn.current,
      abort = new AbortController();
    controller.current = abort;
    setRequestError("");
    if (!next.slotWeights.length && !next.slotMember) {
      setBusy(false);
      setStale(false);
      setData(null);
      return;
    }
    setBusy(true);
    setStale(true);
    const query = new URLSearchParams();
    next.slotWeights.forEach((weight) =>
      query.append("weight", String(weight)),
    );
    next.slotClans.forEach((tag) => query.append("clan", tag));
    if (next.slotMember) query.set("member", next.slotMember);
    if (next.slotTownHall) query.set("town_hall", String(next.slotTownHall));
    query.set(
      "per_weight",
      String(Math.max(3, ...Object.values(next.slotExpanded ?? {}))),
    );
    try {
      const result = checkedSlotResponse(
        await api<SlotResponse>(
          `/strikes/replacements?${query}`,
          "GET",
          undefined,
          { signal: abort.signal },
        ),
      );
      if (current !== turn.current) return;
      setData(result);
      setStale(false);
      if (!typed.current && next.slotMember === draftRef.current.slotMember)
        setText(weightsText(result.slots.map((slot) => slot.weight)));
    } catch (cause) {
      if (current === turn.current && !isExpectedCancel(cause, abort.signal))
        setRequestError(
          cause instanceof Error
            ? cause.message
            : "Slots are unavailable. Try again.",
        );
    } finally {
      if (current === turn.current) setBusy(false);
    }
  }
  function apply(next: SlotSearch, delay = 0) {
    cancel();
    const value = normalizedSlotSearch(next);
    draftRef.current = value;
    setDraft(value);
    published.current = slotSearchKey(value);
    callbacks.current.onSearch(value);
    if (invalid.current) {
      setBusy(false);
      setStale(true);
      return;
    }
    if (delay) {
      setStale(true);
      setBusy(true);
      timer.current = setTimeout(() => void run(value), delay);
    } else void run(value);
  }
  const externalKey = slotSearchKey(search);
  useEffect(() => {
    if (published.current === externalKey) return;
    const next = normalizedSlotSearch(search);
    published.current = externalKey;
    draftRef.current = next;
    setDraft(next);
    const restoredError =
      next.slotWeights.length > 5 ||
      next.slotWeights.some((weight) => weight <= 0 || weight > 500000)
        ? "Enter up to 5 weights, each up to 500k."
        : "";
    invalid.current = !!restoredError;
    typed.current = next.slotWeights.length > 0;
    setText(weightsText(next.slotWeights));
    setInputError(restoredError);
    void run(next);
    // The canonical key binds restored fields, including expansion and duplicate weights.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalKey]);
  useEffect(() => () => cancel(), []);
  useEffect(() => {
    if (disabled) {
      cancel();
      setBusy(false);
    }
  }, [disabled]);
  function weightsChanged(value: string) {
    setText(value);
    typed.current = !!value.trim();
    const parsed = value.trim()
      ? parseWeights(value)
      : { weights: [], error: "" };
    const error =
      parsed.error ||
      (parsed.weights.some((weight) => weight > 500000)
        ? "Enter weights up to 500k."
        : "");
    invalid.current = !!error;
    setInputError(error);
    if (error) {
      cancel();
      setBusy(false);
      setStale(true);
      return;
    }
    apply(
      { ...draftRef.current, slotWeights: parsed.weights, slotExpanded: {} },
      300,
    );
  }
  const groupKeys = slotGroupKeys(data?.slots ?? []);
  const summary = inputError
    ? "Enter valid weights to update results."
    : busy
      ? "Updating slots…"
      : data
        ? data.slots
            .map(
              (group, index) =>
                `${Math.min(group.candidates.length, slotVisibleCount(group, groupKeys[index], draft.slotExpanded ?? {}))} slots for ${compactWeight(group.weight)}`,
            )
            .join(" · ") ||
          data.member_notice ||
          "No saved weights available"
        : "Enter weights or select a member to find slots.";
  const duplicateGuidance =
    !inputError &&
    !busy &&
    !requestError &&
    (!data || (!data.slots.length && !!data.member_notice));
  return (
    <section className="strike-find-slots" aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`}>Find slots</h2>
      <form
        className="strike-slot-filters"
        onSubmit={(event) => {
          event.preventDefault();
          if (!inputError && !disabled) void run(draftRef.current);
        }}
      >
        <StrikeRecruitSelect
          accounts={accounts}
          value={draft.slotMember}
          disabled={disabled}
          onChange={(member) => {
            if (!typed.current) setText("");
            apply({
              ...draftRef.current,
              slotMember: member,
              slotWeights: typed.current ? draftRef.current.slotWeights : [],
              slotExpanded: {},
            });
          }}
        />
        <label className="strike-slot-weights">
          Weights
          <input
            name="recruit-weights"
            inputMode="text"
            enterKeyHint="search"
            autoComplete="off"
            spellCheck={false}
            value={text}
            maxLength={80}
            disabled={disabled}
            placeholder="143, 173, 150…"
            aria-invalid={!!inputError || undefined}
            aria-describedby={`${hintId}${inputError ? ` ${errorId}` : ""}`}
            onChange={(event) => weightsChanged(event.target.value)}
          />
          <small id={hintId}>Up to 5 weights, in k or full values.</small>
          {inputError && (
            <span id={errorId} role="alert">
              {inputError}
            </span>
          )}
        </label>
        <div className="strike-slot-clans">
          <label>
            Clans
            <input
              {...searchInputProps}
              type="search"
              name="slot-clan-search"
              value={clanQuery}
              disabled={disabled}
              placeholder="Find a clan…"
              onChange={(event) => setClanQuery(event.target.value)}
            />
          </label>
          {!!draft.slotClans.length && (
            <div className="strike-slot-clan-chips">
              {draft.slotClans.map((tag) => (
                <button
                  key={tag}
                  type="button"
                  disabled={disabled}
                  aria-label={`Remove ${fwa.find((clan) => clan.tag === tag)?.name || tag}`}
                  onClick={() =>
                    apply({
                      ...draftRef.current,
                      slotClans: draftRef.current.slotClans.filter(
                        (value) => value !== tag,
                      ),
                      slotExpanded: {},
                    })
                  }
                >
                  {fwa.find((clan) => clan.tag === tag)?.name || tag} ×
                </button>
              ))}
            </div>
          )}
          <RosterFilterOptions
            title={
              draft.slotClans.length ? "Selected FWA clans" : "All FWA clans"
            }
            selected={draft.slotClans}
            disabled={disabled}
            onChange={(tags) =>
              apply({ ...draftRef.current, slotClans: tags, slotExpanded: {} })
            }
            options={fwa
              .filter((clan) =>
                `${clan.name} ${clan.tag}`
                  .toLowerCase()
                  .includes(clanQuery.toLowerCase()),
              )
              .map((clan) => ({
                value: clan.tag,
                label: clan.name,
                count: accounts.filter(
                  (row) =>
                    row.current_clan_tag === clan.tag &&
                    row.marked_for_replacement,
                ).length,
              }))}
          />
        </div>
        <label>
          Town Hall
          <select
            aria-label="Slot Town Hall"
            disabled={disabled}
            value={draft.slotTownHall ?? ""}
            onChange={(event) =>
              apply({
                ...draftRef.current,
                slotTownHall: event.target.value
                  ? Number(event.target.value)
                  : null,
                slotExpanded: {},
              })
            }
          >
            <option value="">Any Town Hall</option>
            {Array.from({ length: 19 }, (_, index) => 19 - index).map(
              (hall) => (
                <option key={hall} value={hall}>
                  TH{hall}
                </option>
              ),
            )}
          </select>
        </label>
      </form>
      <p
        className={`strike-slot-live${duplicateGuidance ? " sr-only" : ""}`}
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {summary}
      </p>
      <LoadError
        message={requestError}
        note={data ? "Showing previous results." : undefined}
        busy={busy}
        onRetry={() => void run(draftRef.current)}
      />
      <div
        className={`strike-slot-results${stale ? " is-stale" : ""}`}
        aria-busy={busy || undefined}
      >
        {data ? (
          <SlotResults
            data={data}
            accounts={accounts}
            expanded={draft.slotExpanded ?? {}}
            disabled={disabled || stale}
            onMore={(key, count) =>
              apply({
                ...draftRef.current,
                slotExpanded: {
                  ...draftRef.current.slotExpanded,
                  [key]: count,
                },
              })
            }
            onChoose={onChoose}
          />
        ) : (
          !busy &&
          !requestError && (
            <EmptyState
              title="No weights selected"
              line="Enter weights or select a member to find slots."
            />
          )
        )}
      </div>
    </section>
  );
}

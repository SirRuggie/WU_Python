import { useState, type SetStateAction } from "react";
import {
  parseRosterReleasePreferences,
  type RosterReleasePreferences,
} from "./rosterReleaseModel";

export const ROSTER_ORDER_KEY = "wu-roster-order-v1";
type StoragePort = Pick<Storage, "getItem" | "setItem">;

/** Only ordering crosses seasons/devices sessions; filters stay season-scoped. */
export function readRosterPreferences(
  key: string,
  session: () => StoragePort,
  local: () => StoragePort,
): RosterReleasePreferences {
  let filters = parseRosterReleasePreferences(null);
  try {
    filters = parseRosterReleasePreferences(session().getItem(key));
  } catch {
    /* Optional storage. */
  }
  let order = parseRosterReleasePreferences(null);
  try {
    order = parseRosterReleasePreferences(local().getItem(ROSTER_ORDER_KEY));
  } catch {
    /* Safe default. */
  }
  return { ...filters, sort: order.sort, grouped: order.grouped };
}

export function saveRosterPreferences(
  key: string,
  value: RosterReleasePreferences,
  session: () => StoragePort,
  local: () => StoragePort,
) {
  const valid = parseRosterReleasePreferences(value);
  try {
    session().setItem(key, JSON.stringify(valid));
  } catch {
    /* Optional storage. */
  }
  try {
    local().setItem(
      ROSTER_ORDER_KEY,
      JSON.stringify({ sort: valid.sort, grouped: valid.grouped }),
    );
  } catch {
    /* Optional storage. */
  }
  return valid;
}

export default function useRosterPreferences(seasonId: string) {
  const key = `wu-roster-${seasonId}-release-v1`;
  const read = () =>
    readRosterPreferences(
      key,
      () => sessionStorage,
      () => localStorage,
    );
  const [state, setState] = useState(() => ({ key, value: read() }));
  if (state.key !== key) setState({ key, value: read() });
  const update = (next: SetStateAction<RosterReleasePreferences>) =>
    setState((current) => {
      const previous = current.key === key ? current.value : read();
      const result = typeof next === "function" ? next(previous) : next;
      return {
        key,
        value: saveRosterPreferences(
          key,
          result,
          () => sessionStorage,
          () => localStorage,
        ),
      };
    });
  return [state.key === key ? state.value : read(), update] as const;
}

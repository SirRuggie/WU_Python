/** Tab-scoped explicit Start intent only. No server data or automatic writes. */
export type StartOperation = {
  actor: string;
  cycle: string;
  openSignups: boolean;
  seen: { season_id: number; revision: number };
  error?: string;
};
const prefix = "wu:season-start:";
export function readStartOperation(actor: string): StartOperation | null {
  try {
    const raw = sessionStorage.getItem(prefix + actor);
    if (!raw || raw.length > 4000) return null;
    const value = JSON.parse(raw) as StartOperation;
    return value.actor === actor &&
      /^\d{4}-(0[1-9]|1[0-2])$/.test(value.cycle) &&
      typeof value.openSignups === "boolean" &&
      Number.isSafeInteger(value.seen?.season_id) &&
      value.seen.season_id > 0 &&
      Number.isSafeInteger(value.seen.revision) &&
      value.seen.revision >= 0 &&
      (value.error === undefined || typeof value.error === "string")
      ? value
      : null;
  } catch {
    return null;
  }
}
export function saveStartOperation(value: StartOperation): boolean {
  if (!value.actor) return true; // Embedded component fixtures have no signed-in actor.
  try {
    sessionStorage.setItem(prefix + value.actor, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}
export function clearStartOperation(actor?: string, keepActor?: string) {
  try {
    for (const key of Object.keys(sessionStorage)) {
      if (
        key.startsWith(prefix) &&
        (actor ? key === prefix + actor : key !== prefix + keepActor)
      )
        sessionStorage.removeItem(key);
    }
  } catch {
    /* Reads/mutations remain independently permission checked. */
  }
}

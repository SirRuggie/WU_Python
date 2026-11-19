/** Presentation only: exact stored values remain available to history restore. */
export function isTownHallHistoryTarget(target: string) {
  return /\/manage\/town-halls(?:\/(?:[1-9][0-9]?|settings))?$/.test(target);
}

export function townHallHistoryValue(
  target: string,
  key: string,
  value: unknown,
) {
  if (!isTownHallHistoryTarget(target) || key !== "emoji") return null;
  if (value === "" || value === null || value === undefined) return "None";
  const match =
    typeof value === "string"
      ? /^<a?:([A-Za-z0-9_]{2,32}):[0-9]{15,22}>$/.exec(value)
      : null;
  return match ? match[1] : "Emoji unavailable";
}

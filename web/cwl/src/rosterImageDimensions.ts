/** Matches the existing deterministic utils/cwl_roster_render.py page geometry. */
export function rosterImageDimensions(count: number, zeroBasedPage: number) {
  if (
    !Number.isInteger(count) ||
    count <= 0 ||
    !Number.isInteger(zeroBasedPage) ||
    zeroBasedPage < 0
  )
    return {};
  const rows = Math.min(15, count - zeroBasedPage * 15);
  return rows > 0 ? { width: 1000, height: 390 + rows * 70 } : {};
}

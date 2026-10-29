export type Box = { top: number; left: number; width: number; height: number };
/** Try both sides, then below/above. Never clamp a side into the target. */
export function placeCard(
  target: Box,
  card: { width: number; height: number },
  viewport: { width: number; height: number },
) {
  const gap = 24,
    edge = 12;
  const top = Math.max(
    edge,
    Math.min(target.top, viewport.height - card.height - edge),
  );
  const left = Math.max(
    edge,
    Math.min(target.left, viewport.width - card.width - edge),
  );
  const candidates = [
    { left: target.left + target.width + gap, top },
    { left: target.left - card.width - gap, top },
    { left, top: target.top + target.height + gap + 40 },
    { left, top: target.top - card.height - gap },
  ];
  return (
    candidates.find(
      (p) =>
        p.left >= edge &&
        p.top >= edge &&
        p.left + card.width <= viewport.width - edge &&
        p.top + card.height <= viewport.height - edge,
    ) ?? candidates[2]
  );
}

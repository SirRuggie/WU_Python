/** Keep in parity with utils/cwl_lazy_rule.py. */
export const LAZY_MIN_ATTACKS = 4;
export const LAZY_ALT_ATTACKS = 3;
export const LAZY_ALT_STARS = 8;
export const LAZY_RULE_SHORT = "4+ attacks, or 3 attacks and 8+ stars";

export function lazyQualifies(attacks: number, stars: number): boolean {
  return (
    attacks >= LAZY_MIN_ATTACKS ||
    (attacks >= LAZY_ALT_ATTACKS && stars >= LAZY_ALT_STARS)
  );
}

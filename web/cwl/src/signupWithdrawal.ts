/** Stop after the first error, retaining only confirmed deletions. No retries. */
export async function withdrawInOrder(
  tags: string[],
  remove: (tag: string) => Promise<unknown>,
) {
  const removed = new Set<string>();
  for (const tag of new Set(tags)) {
    try {
      await remove(tag);
      removed.add(tag);
    } catch (error) {
      return { removed, error };
    }
  }
  return { removed, error: null };
}

type PlacementSignup = {
  tag: string;
  player_name?: string | null;
  has_staff_placement?: boolean;
};
const placedAccountNames = (rows: readonly PlacementSignup[]) =>
  rows
    .filter((row) => row.has_staff_placement)
    .map((row) => row.player_name || row.tag);

export function signupPlacementNotice(
  rows: readonly PlacementSignup[],
): string | null {
  const names = placedAccountNames(rows);
  return names.length
    ? `Changing pools or withdrawing will clear the clan assignment${names.length === 1 ? "" : "s"} for ${names.join(", ")} and alert staff.`
    : null;
}

export function withdrawConfirmation(rows: readonly PlacementSignup[]): string {
  const names = rows
    .map((row) => `${row.player_name || row.tag} (${row.tag})`)
    .join("\n");
  const placed = placedAccountNames(rows);
  return `Withdraw ${rows.length} ${rows.length === 1 ? "account" : "accounts"} from this season's CWL signup?\n\n${names}${placed.length ? `\n\nClan assignments will be cleared for: ${placed.join(", ")}. Staff will be alerted.` : ""}`;
}

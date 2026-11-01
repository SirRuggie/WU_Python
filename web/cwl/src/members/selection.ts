/** Selection is a stable set of IDs, independent of filtering and pagination. */
export type SelectableMember = { discord_id: string; bot: boolean };
export function toggleMember(selected: ReadonlySet<string>, id: string) {
  const next = new Set(selected);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  return next;
}
export function selectPage(
  selected: ReadonlySet<string>,
  page: readonly SelectableMember[],
) {
  return new Set([
    ...selected,
    ...page.filter((row) => !row.bot).map((row) => row.discord_id),
  ]);
}
export function selectMatching(
  selected: ReadonlySet<string>,
  matching: readonly SelectableMember[],
) {
  return selectPage(selected, matching);
}
export function selectionSummary(
  selected: ReadonlySet<string>,
  visible: readonly SelectableMember[],
) {
  const ids = new Set(visible.map((row) => row.discord_id));
  const onPage = visible.filter(
    (row) => !row.bot && selected.has(row.discord_id),
  ).length;
  const selectable = visible.filter((row) => !row.bot).length;
  return {
    count: selected.size,
    hidden: [...selected].filter((id) => !ids.has(id)).length,
    all: selectable > 0 && onPage === selectable,
    partial: onPage > 0 && onPage < selectable,
  };
}
/** Freeze the exact reviewed IDs; changes to filters never alter a confirmation. */
export function confirmedTargets(
  selected: ReadonlySet<string>,
  known: readonly SelectableMember[],
) {
  const available = new Map(known.map((row) => [row.discord_id, row]));
  const ids = [...selected].sort();
  if (ids.some((id) => !available.has(id) || available.get(id)!.bot))
    throw new Error("Selection changed. Review the selected people.");
  return Object.freeze(ids);
}

/** Stop after the first error, retaining only confirmed deletions. No retries. */
export async function withdrawInOrder(tags: string[], remove: (tag: string) => Promise<unknown>) {
  const removed = new Set<string>()
  for (const tag of new Set(tags)) {
    try { await remove(tag); removed.add(tag) }
    catch (error) { return {removed, error} }
  }
  return {removed, error: null}
}

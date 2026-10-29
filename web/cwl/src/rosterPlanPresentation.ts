import type { AutoPreview, RosterAccount, RosterClan } from './roster'
export function rosterWeightSummary(accounts: RosterAccount[]) {
  const known = accounts.filter(a => a.effective_weight !== null)
  return { count: accounts.length, weighed: known.length,
    average: known.length ? Math.round(known.reduce((sum, a) => sum + a.effective_weight!, 0) / known.length) : null }
}
export function planPresentation(accounts: RosterAccount[], clans: RosterClan[], preview: AutoPreview, candidates: string[], targets: string[]) {
  const changes = new Map(preview.placements.map(p => [p.tag, p.assigned_clan_tag]))
  const skipped = new Set(preview.unassigned.map(p => p.tag))
  const affected = new Set([...targets, ...preview.placements.map(p => p.assigned_clan_tag),
    ...accounts.filter(a => changes.has(a.tag)).map(a => a.assigned_clan_tag)])
  const projected = accounts.map(a => changes.has(a.tag) ? { ...a, assigned_clan_tag: changes.get(a.tag)! } : a)
  return {
    clans: clans.filter(c => affected.has(c.tag)).map(clan => ({clan,
      before: rosterWeightSummary(accounts.filter(a => a.assigned_clan_tag === clan.tag)),
      after: rosterWeightSummary(projected.filter(a => a.assigned_clan_tag === clan.tag))})),
    unchanged: accounts.filter(a => candidates.includes(a.tag) && !changes.has(a.tag) && !skipped.has(a.tag)),
  }
}
export function publishedMoveCount(preview: AutoPreview, published: {tag:string; assigned_clan_tag:string|null}[]) {
  const assigned = new Map(published.filter(a => a.assigned_clan_tag).map(a => [a.tag,a.assigned_clan_tag]))
  return preview.placements.filter(p => assigned.has(p.tag) && assigned.get(p.tag) !== p.assigned_clan_tag).length
}

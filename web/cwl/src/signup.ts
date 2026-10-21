import type { Account, Pool, Signup } from './api'
export type Draft = Record<string, boolean>
export type TransferConsent = Record<string, Pool>
export type SignupSelection = { tag: string; prefer_crystal_1_or_lower: boolean; move_from_pool?: Pool }
export function accountPool(signups: Signup[], tag: string): Pool | undefined { return signups.find(signup => signup.tag === tag)?.pool }
export function transferSource(signups: Signup[], tag: string, destination: Pool): Pool | undefined {
  const source = accountPool(signups, tag)
  return source && source !== destination ? source : undefined
}
export function selectable(account: Account, pool: Pool, signups: Signup[]): boolean { const existing = accountPool(signups, account.tag); return !existing || existing === pool }
export function selectedEntries(accounts: Account[], draft: Draft, transfers: TransferConsent = {}): SignupSelection[] {
  return accounts.filter(account => Object.hasOwn(draft, account.tag)).map(account => ({
    tag: account.tag,
    prefer_crystal_1_or_lower: draft[account.tag],
    ...(transfers[account.tag] ? { move_from_pool: transfers[account.tag] } : {}),
  }))
}
export function selectedForPool(accounts: Account[], draft: Draft, signups: Signup[], pool: Pool, transfers: TransferConsent): SignupSelection[] {
  return selectedEntries(accounts.filter(account => selectable(account, pool, signups) || transfers[account.tag] === transferSource(signups, account.tag, pool)), draft, transfers)
}
export function selectAllAvailable(accounts: Account[], pool: Pool, signups: Signup[], draft: Draft, transfers: TransferConsent): Draft {
  const keptTransfers = Object.fromEntries(Object.entries(draft).filter(([tag]) => transfers[tag] === transferSource(signups, tag, pool) && transfers[tag] !== undefined))
  const ordinary = accounts.filter(account => selectable(account, pool, signups)).map(account => [account.tag, draft[account.tag] ?? signups.find(signup => signup.tag === account.tag && signup.pool === pool)?.prefer_crystal_1_or_lower ?? false])
  return { ...keptTransfers, ...Object.fromEntries(ordinary) }
}
export function seedDraft(accounts: Account[], signups: Signup[], pool: Pool): Draft { const tags = new Set(accounts.map(account => account.tag)); return Object.fromEntries(signups.filter(signup => signup.pool === pool && tags.has(signup.tag)).map(signup => [signup.tag, signup.prefer_crystal_1_or_lower])) }
export function submittedSummary(accounts: Account[], selected: SignupSelection[]) {
  const byTag = new Map(accounts.map(account => [account.tag, account]))
  return selected.map(item => ({ tag: item.tag, name: byTag.get(item.tag)?.name || item.tag, prefer_crystal_1_or_lower: item.prefer_crystal_1_or_lower, move_from_pool: item.move_from_pool }))
}
export function clearSubmittedDraft(drafts: Record<Pool, Draft>, submittedPool: Pool): Record<Pool, Draft> { return { ...drafts, [submittedPool]: {} } }

/** A refreshed owner/pool must never silently retain consent for an old move. */
export function reconcileSelection(draft: Draft, transfers: TransferConsent, accounts: Account[], signups: Signup[], pool: Pool) {
  const tags = new Set(accounts.map(account => account.tag))
  const kept: Draft = {}
  const consent: TransferConsent = {}
  for (const [tag, preference] of Object.entries(draft)) {
    if (!tags.has(tag)) continue
    const source = transferSource(signups, tag, pool)
    if (source && transfers[tag] !== source) continue
    if (transfers[tag] && transfers[tag] !== source) continue
    kept[tag] = preference
    if (source) consent[tag] = source
  }
  return { draft: kept, transfers: consent }
}

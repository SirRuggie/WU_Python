import type { Pool } from './api'

export type BonusPolicy = { min_attacks: number | null; min_stars: number | null; cooldown_months: number | null }
export type BonusClan = { tag: string; name: string; slots: number | null }
export type PreviousBonus = { cycle: string; confirmed_at: string; season_id: number; clan_tag: string | null }
export type BonusAccount = {
  tag: string; player_name: string; pool: Pool; assigned_clan_tag: string | null; assigned_clan_name: string | null;
  attacks: number | null; stars: number | null; source_status: string; source_warning: string | null;
  last_confirmed_bonus: PreviousBonus | null; recommended: boolean | null; eligibility_reason: string | null;
  source_complete: boolean; already_confirmed_this_cycle: boolean; selected: boolean; reason: string
}
export type BonusHistory = {
  id: number; tag: string; player_name: string; clan_tag: string | null; clan_name: string | null;
  cycle: string; publication_version: number; attacks: number | null; stars: number | null; reason: string;
  confirmed_by: string; confirmed_at: string; voided_by: string | null; voided_at: string | null; void_reason: string | null; warnings?: string[]
}
export type BonusData = { cycle: string | null; revision: number; policy: BonusPolicy; clans: BonusClan[]; accounts: BonusAccount[]; history: BonusHistory[]; cycle_confirmed: { id: number; tag: string; clan_tag: string | null; season_id: number }[]; active_other_cycles: string[]; history_scope: 'dashboard_confirmations_only'; award_status: string }
export type BonusSelection = { tag: string; reason: string }
export type BonusPreview = { revision: number; fingerprint: string; selected: BonusAccount[]; warnings: string[]; capacity: { clan_tag: string; clan_name: string; slots: number | null; selected_count: number; confirmed_count: number }[]; blocking_reasons: string[]; can_confirm: boolean; award_status: string }
export const PAGE_SIZE = 8

export function selectionsFromAccounts(accounts: BonusAccount[]): Record<string, string> {
  return Object.fromEntries(accounts.filter(account => account.selected).map(account => [account.tag, account.reason || '']))
}
export function selectionsPayload(selected: Record<string, string>): BonusSelection[] {
  return Object.entries(selected).map(([tag, reason]) => ({ tag, reason: reason.trim() })).sort((a, b) => a.tag.localeCompare(b.tag))
}
export function selectionsChanged(accounts: BonusAccount[], selected: Record<string, string>): boolean {
  return JSON.stringify(selectionsPayload(selectionsFromAccounts(accounts))) !== JSON.stringify(selectionsPayload(selected))
}
export function selectionReasonError(accounts: BonusAccount[], selected: Record<string, string>): string | null {
  const byTag = new Map(accounts.map(account => [account.tag, account]))
  for (const [tag, reason] of Object.entries(selected)) {
    const account = byTag.get(tag)
    if (!account) return 'A selected account is no longer in this published roster. Refresh and review.'
    if (reason.length > 500) return `Keep the reason for ${account.player_name} within 500 characters.`
  }
  return null
}
export function parseNullableWhole(value: string, min: number, max: number): number | null | undefined {
  if (!value.trim()) return null
  if (!/^\d+$/.test(value.trim())) return undefined
  const parsed = Number(value.trim())
  return parsed >= min && parsed <= max ? parsed : undefined
}
export function pageItems<T>(items: T[], page: number): T[] { return items.slice(Math.max(0, page) * PAGE_SIZE, (Math.max(0, page) + 1) * PAGE_SIZE) }

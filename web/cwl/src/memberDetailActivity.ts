export type ActivitySummary = {
  state?: unknown
  my_accounts?: unknown
  clan?: unknown
  opponent?: unknown
  starts_at?: unknown
  ends_at?: unknown
}

export type ClanActivityRow = {
  tag?: unknown
  name?: unknown
  accounts?: unknown
  regular?: ActivitySummary | null
  cwl?: ActivitySummary | null
}

export type ActivitySnapshot = {
  checked_at?: unknown
  clans?: unknown
  warnings?: unknown
}

export type MemberWarActivity = {
  checkedAt: string | null
  warning: string | null
  regular: ActivitySummary | null
  regularClan: {tag: string; name: string} | null
  cwl: ActivitySummary | null
  cwlClan: {tag: string; name: string} | null
}

function validTag(value: unknown): value is string {
  return typeof value === 'string' && /^#[A-Z0-9]{3,12}$/i.test(value)
}

function rowClan(row: ClanActivityRow): {tag: string; name: string} | null {
  if (!validTag(row.tag)) return null
  return {tag: row.tag, name: typeof row.name === 'string' && row.name.trim() ? row.name : row.tag}
}

function accountsContain(accounts: unknown, tag: string): boolean {
  return Array.isArray(accounts) && accounts.some(account =>
    account && typeof account === 'object' && validTag((account as {tag?: unknown}).tag) &&
    (account as {tag: string}).tag.toUpperCase() === tag.toUpperCase())
}

function summary(value: unknown): ActivitySummary | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as ActivitySummary : null
}

function playerSummaryContains(summaryValue: ActivitySummary | null | undefined, tag: string): boolean {
  return accountsContain(summaryValue?.my_accounts, tag)
}

export function matchingWarActivity(
  snapshot: ActivitySnapshot | null | undefined,
  target: 'player' | 'clan',
  tag: string,
  clanTag?: string | null,
): MemberWarActivity | null {
  if (!snapshot || typeof snapshot !== 'object' || !Array.isArray(snapshot.clans)) return null
  const rows = snapshot.clans.filter((row): row is ClanActivityRow => !!row && typeof row === 'object' && !Array.isArray(row))
  let regular: ActivitySummary | null = null
  let regularClan: {tag: string; name: string} | null = null
  let cwl: ActivitySummary | null = null
  let cwlClan: {tag: string; name: string} | null = null

  if (target === 'clan') {
    const row = rows.find(item => validTag(item.tag) && item.tag.toUpperCase() === tag.toUpperCase())
    if (!row) return null
    regular = summary(row.regular)
    regularClan = rowClan(row)
    cwl = summary(row.cwl)
    cwlClan = cwl ? rowClan(row) : null
  } else {
    // Current regular war follows the account's current hosting clan, while CWL
    // can remain on a recent hosting clan after the account has returned home.
    const currentRow = rows.find(item =>
      validTag(item.tag) && accountsContain(item.accounts, tag) &&
      (!clanTag || item.tag.toUpperCase() === clanTag.toUpperCase()))
    if (currentRow) {
      regular = summary(currentRow.regular)
      regularClan = rowClan(currentRow)
    }

    const hostingCwl = rows.find(item => validTag(item.tag) && playerSummaryContains(summary(item.cwl), tag))
    if (hostingCwl) {
      cwl = personalSummary(summary(hostingCwl.cwl), tag)
      cwlClan = rowClan(hostingCwl)
    } else if (currentRow) {
      const currentCwl = summary(currentRow.cwl)
      if (currentCwl?.state === 'private' || currentCwl?.state === 'error') {
        cwl = personalSummary(currentCwl, tag)
        cwlClan = rowClan(currentRow)
      }
    }
  }

  const checked = typeof snapshot.checked_at === 'string' && Number.isFinite(Date.parse(snapshot.checked_at))
    ? new Date(snapshot.checked_at).toISOString() : null
  const warnings = Array.isArray(snapshot.warnings)
    ? snapshot.warnings.filter((value): value is string => typeof value === 'string' && !!value.trim()).slice(0, 2)
    : []
  return {
    checkedAt: checked,
    warning: warnings.length ? warnings.join(' ') : null,
    regular: target === 'player' ? personalSummary(regular, tag) : regular,
    regularClan,
    cwl: target === 'player' ? personalSummary(cwl, tag) : cwl,
    cwlClan,
  }
}

function personalSummary(summaryValue: ActivitySummary | null | undefined, tag: string): ActivitySummary | null {
  if (!summaryValue) return null
  if (!Array.isArray(summaryValue.my_accounts)) return summaryValue
  const accounts = summaryValue.my_accounts.filter(account => account && typeof account === 'object' && validTag((account as {tag?: unknown}).tag) && (account as {tag: string}).tag.toUpperCase() === tag.toUpperCase())
  return {...summaryValue, my_accounts: accounts}
}

export function activityState(summaryValue: ActivitySummary | null): string {
  const value = summaryValue?.state
  if (value === 'none') return 'No war returned.'
  if (value === 'private') return 'War details are private.'
  if (value === 'error' || !summaryValue || typeof value !== 'string') return 'War details are unavailable.'
  if (value === 'preparation') return 'Preparation day'
  if (value === 'inWar') return 'War in progress'
  if (value === 'warEnded') return 'War ended.'
  if (value === 'awaitingResult') return 'War ended · results pending'
  return 'War details are unavailable.'
}

export function ownAttackText(summaryValue: ActivitySummary | null, tag: string): string | null {
  if (!summaryValue || !Array.isArray(summaryValue.my_accounts)) return null
  const account = summaryValue.my_accounts.find(value => value && typeof value === 'object' && validTag((value as {tag?: unknown}).tag) && (value as {tag: string}).tag.toUpperCase() === tag.toUpperCase()) as {attacks_left?: unknown; attacks_total?: unknown} | undefined
  if (!account) {
    return summaryValue.state === 'preparation' || summaryValue.state === 'inWar'
      ? 'This account is not listed in this war.'
      : null
  }
  const left = account.attacks_left
  const total = account.attacks_total
  if (typeof left !== 'number' || typeof total !== 'number' || !Number.isSafeInteger(left) || !Number.isSafeInteger(total) || total <= 0 || left < 0 || left > total) {
    return 'Attack count unavailable.'
  }
  return `${total - left}/${total} attacks used`
}

export function formatCheckedAt(value: string | null): string | null {
  if (!value) return null
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date.toLocaleString() : null
}

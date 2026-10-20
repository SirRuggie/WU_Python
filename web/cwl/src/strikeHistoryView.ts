export function strikeBadge(kind: 'strike' | 'miss' | 'completed', status: string): string {
  if (status === 'exempt') return 'Exempt'
  if (kind === 'completed') return 'Attacks done'
  if (kind === 'miss') return status === 'completed' ? 'Attacks done' : 'One missed'
  if (status === 'active') return 'Active strike'
  return `${status[0]?.toUpperCase() || ''}${status.slice(1)} strike`
}

export function warMatchup(clanName?: string | null, opponentName?: string | null): string {
  const clan = clanName || 'Unknown clan'
  return opponentName ? `${clan} vs ${opponentName}` : clan
}

export function detailQuery(page: number, status: string, playerTag?: string, warKey?: string): URLSearchParams {
  const params = new URLSearchParams({ limit: '25', offset: String(page * 25), status })
  if (playerTag) params.set('query', playerTag)
  if (warKey) params.set('war_key', warKey)
  return params
}

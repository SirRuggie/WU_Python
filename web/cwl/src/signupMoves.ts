import type {Account, Pool, Signup} from './api'
export type SignupMove = {signup: Signup; destination: Pool}
/** Each destination is atomic on the server. Stop on errors; never retry silently. */
export async function saveSignupMoves(moves: SignupMove[], save: (pool: Pool, rows: Signup[]) => Promise<unknown>) {
  const saved: string[] = []
  for (const pool of ['main', 'lazy'] as Pool[]) {
    const rows = moves.filter(move => move.destination === pool && move.signup.pool !== pool).map(move => move.signup)
    if (!rows.length) continue
    try { await save(pool, rows); saved.push(...rows.map(row => row.tag)) }
    catch (error) { return {saved, error} }
  }
  return {saved, error: null}
}

/** Only actual changes need confirmation; undoing a draft never moves a signup. */
export function poolChangeDecision(rows: Signup[], destination: Pool, accounts: Account[]) {
  if (!rows.length || rows.some(row => !accounts.some(account => account.tag === row.tag))) return 'unavailable'
  const changing = rows.filter(row => row.pool !== destination)
  if (destination === 'main' && changing.some(row => accounts.find(account => account.tag === row.tag)?.current_clan_type === 'FWA')) return 'fwa'
  return changing.length ? 'confirm' : 'undo'
}

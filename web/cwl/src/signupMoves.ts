import type {Pool, Signup} from './api'
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

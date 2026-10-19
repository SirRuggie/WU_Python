export type AssignmentTarget = { season: string }
const storageKey = 'wu-cwl-assignment-target'
export function parseAssignmentTarget(search: string): AssignmentTarget | null {
  const params = new URLSearchParams(search)
  const season = params.get('season') || ''
  return params.get('view') === 'assignments' && /^\d+$/.test(season) ? { season } : null
}
export function rememberAssignmentTarget(search: string, storage: Pick<Storage, 'setItem'>): void {
  const target = parseAssignmentTarget(search)
  if (target) storage.setItem(storageKey, target.season)
}
export function initialAssignmentTarget(search: string, storage: Pick<Storage, 'getItem' | 'removeItem'>): AssignmentTarget | null {
  const direct = parseAssignmentTarget(search)
  if (direct) return direct
  const stored = storage.getItem(storageKey) || ''
  storage.removeItem(storageKey)
  return /^\d+$/.test(stored) ? { season: stored } : null
}

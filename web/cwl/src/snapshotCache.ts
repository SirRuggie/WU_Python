// Display-only snapshots. Permissions and every mutation still use live APIs.
const prefix = 'wu-snapshot-v1:'
const lifetime = 5 * 60 * 1000
export function readSnapshot<T>(key: string, valid: (value: unknown) => value is T, storage?: Pick<Storage, 'getItem'>, now = Date.now()): T | null {
  try {
    const entry = JSON.parse((storage ?? window.localStorage).getItem(prefix + key) || 'null')
    if (!entry || typeof entry.savedAt !== 'number' || now < entry.savedAt || now - entry.savedAt > lifetime || !valid(entry.data)) return null
    return entry.data
  } catch { return null }
}
export function writeSnapshot(key: string, data: unknown, storage?: Pick<Storage, 'setItem'>, now = Date.now()) {
  try { (storage ?? window.localStorage).setItem(prefix + key, JSON.stringify({ savedAt: now, data })) } catch { /* Cache is optional. */ }
}
export function clearSnapshots() {
  try { for (const key of Object.keys(window.localStorage)) if (key.startsWith(prefix)) window.localStorage.removeItem(key) } catch { /* Storage may be blocked. */ }
}

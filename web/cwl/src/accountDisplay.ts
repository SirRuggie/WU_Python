import { api, ApiError, type Account } from './api'

export type AccountDisplay = {
  accounts: Account[]; updating?: boolean; total?: number | null;
  error?: string | null; link_instruction: string;
}

// Keep visible selections stable while a refresh is incomplete. Only a complete,
// successful link read may remove an account from the display.
export function mergeAccountProgress(previous: Account[], snapshot: AccountDisplay): Account[] {
  if (!snapshot.updating && !snapshot.error) return snapshot.accounts
  const merged = new Map(previous.map(account => [account.tag, account]))
  for (const account of snapshot.accounts) merged.set(account.tag, account)
  return [...merged.values()]
}

// A partial list is display-only. Callers keep save controls blocked until completion.
export async function loadAccountDisplay(
  onProgress: (snapshot: AccountDisplay) => void,
  active: () => boolean,
  refresh = false,
): Promise<AccountDisplay> {
  const deadline = Date.now() + 135_000
  let first = true
  while (active()) {
    if (Date.now() >= deadline) throw new Error('Account details are taking longer than expected. Refresh accounts to try again.')
    if (!first && document.hidden) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      continue
    }
    const snapshot = await api<AccountDisplay>(`/linked-accounts?background=1${first && refresh ? '&refresh=1' : ''}`)
    first = false
    if (!active()) throw new DOMException('Account loading cancelled', 'AbortError')
    onProgress(snapshot)
    if (!snapshot.updating) {
      if (snapshot.error) throw new ApiError(snapshot.error, 503)
      return snapshot
    }
    await new Promise(resolve => setTimeout(resolve, 750))
  }
  throw new DOMException('Account loading cancelled', 'AbortError')
}

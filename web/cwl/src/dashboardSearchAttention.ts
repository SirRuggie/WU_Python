import type {AttentionItem} from './AttentionSummary'

export function dashboardSearchAttention(error: string, familyError: string, busy: boolean, onRefresh: () => void): AttentionItem[] {
  const items: AttentionItem[] = []
  if (error) {
    const accessChanged = error.startsWith('Your dashboard access changed')
    items.push({
      title: accessChanged ? 'Dashboard access changed' : 'Linked accounts are unavailable',
      detail: accessChanged ? 'Refresh or sign in again to continue searching.' : 'Search results may be incomplete. Retry search data.',
      technicalDetail: error,
      action: { label: 'Refresh search data', onClick: onRefresh, disabled: busy },
    })
  }
  if (familyError) {
    items.push({
      title: 'Staff family clan directory is unavailable',
      detail: 'Search is limited to linked accounts and their clans.',
      technicalDetail: familyError,
      ...(!error ? { action: { label: 'Refresh search data', onClick: onRefresh, disabled: busy } } : {}),
    })
  }
  return items
}

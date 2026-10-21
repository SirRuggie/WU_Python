export type MemberView = 'home' | 'search' | 'wars' | 'events' | 'todo' | 'signup' | 'assignments'
export function memberTarget(search: string): {view: MemberView; season: string} {
  const params = new URLSearchParams(search)
  const value = params.get('view') === 'signups' ? 'signup' : params.get('view')
  const view = (['home', 'search', 'wars', 'events', 'todo', 'signup', 'assignments'].includes(value || '') ? value : 'home') as MemberView
  const season = params.get('season') || ''
  return {view, season: ['signup','assignments'].includes(view) && /^\d{1,18}$/.test(season) ? season : ''}
}
export function memberPath(view: string, season = ''): string {
  const target = memberTarget(`?${new URLSearchParams({view, season})}`)
  const params = new URLSearchParams({view: target.view})
  if (target.season) params.set('season', target.season)
  return `/?${params}`
}
export function loginPath(search: string, retry: boolean): string {
  const target = memberTarget(search)
  const params = new URLSearchParams({view: target.view})
  if (target.season) params.set('season', target.season)
  if (retry) params.set('retry','1')
  return `/api/cwl/auth/discord?${params}`
}

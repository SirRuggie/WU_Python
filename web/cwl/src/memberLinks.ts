export type MemberView = 'home' | 'search' | 'wars' | 'events' | 'todo' | 'signup' | 'assignments'
export const memberPaths: Record<string, string> = {home: '/', signup: '/signup', assignments: '/assignments', todo: '/tasks', wars: '/wars', events: '/events', search: '/search'}
export function memberTarget(search: string, pathname = '/'): {view: MemberView; season: string} {
  const params = new URLSearchParams(search)
  const pathView = Object.entries(memberPaths).find(([, path]) => path === pathname && path !== '/')?.[0]
  const value = pathView || (params.get('view') === 'signups' ? 'signup' : params.get('view'))
  const view = (['home', 'search', 'wars', 'events', 'todo', 'signup', 'assignments'].includes(value || '') ? value : 'home') as MemberView
  return {view, season: ''}
}
export function memberPath(view: string, _season = ''): string {
  return memberPaths[view] || '/'
}
export function loginPath(search: string, retry: boolean, pathname = '/'): string {
  const target = memberTarget(search, pathname)
  const params = new URLSearchParams({view: target.view})
  if (target.season) params.set('season', target.season)
  if (retry) params.set('retry','1')
  return `/api/cwl/auth/discord?${params}`
}

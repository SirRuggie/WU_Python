import { cwlTarget } from "./staffLinks"
export type MemberView = 'home' | 'search' | 'wars' | 'events' | 'todo' | 'signup' | 'assignments'
export const memberPaths: Record<string, string> = {home: '/', signup: '/signup', assignments: '/assignments', todo: '/tasks', wars: '/wars', events: '/events', search: '/search'}
export function savedSignupTarget(search: string, pathname = '/'): boolean {
  const params = new URLSearchParams(search)
  return pathname.replace(/\/$/, '') === '/my-signups' ||
    (pathname === '/' && params.get('view') === 'my-signups') ||
    ((pathname.replace(/\/$/, '') === '/signup' || (pathname === '/' && ['signup','signups'].includes(params.get('view') || ''))) && params.get('tab') === 'saved')
}
export function memberTarget(search: string, pathname = '/'): {view: MemberView; season: string; signupPanel?: 'saved'} {
  const params = new URLSearchParams(search)
  pathname = pathname === '/' ? '/' : pathname.replace(/\/$/, '')
  const saved = savedSignupTarget(search, pathname)
  const pathView = Object.entries(memberPaths).find(([, path]) => path === pathname && path !== '/')?.[0]
  const value = (saved ? 'signup' : pathView) || (params.get('view') === 'signups' ? 'signup' : params.get('view'))
  const view = (['home', 'search', 'wars', 'events', 'todo', 'signup', 'assignments'].includes(value || '') ? value : 'home') as MemberView
  return {view, season: '', ...(saved ? {signupPanel: 'saved' as const} : {})}
}
export function memberPath(view: string, _season = ''): string {
  return memberPaths[view] || '/'
}
export function loginPath(search: string, retry: boolean, pathname = '/'): string {
  const weightPage = ['/clan-weights','/weight','/weights','/weight-trial'].includes(pathname.replace(/\/$/, '')) || (pathname === '/' && new URLSearchParams(search).get('view') === 'weight-trial')
  const staffView = cwlTarget(search, pathname)
  const target = memberTarget(search, pathname)
  const params = new URLSearchParams({view: staffView || (weightPage ? 'weight-trial' : target.signupPanel === 'saved' ? 'my-signups' : target.view)})
  const incoming = new URLSearchParams(search)
  if (staffView && /^\d{1,18}$/.test(incoming.get('season') || '')) params.set('season', incoming.get('season')!)
  if (staffView === 'publication' && ['review','announce'].includes(incoming.get('step') || '')) params.set('step', incoming.get('step')!)
  if (target.season) params.set('season', target.season)
  if (retry) params.set('retry','1')
  return `/api/cwl/auth/discord?${params}`
}

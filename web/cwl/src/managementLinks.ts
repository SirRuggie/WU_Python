// Page destinations only; each API remains responsible for authorization.
export const managementPaths: Record<string, string> = {
  'staff-overview': '/staff',
  'clan-management': '/clans',
  strikes: '/clans/strikes',
  replacements: '/clans/replacements',
  'members-settings': '/server/members',
  'member-activity': '/server/member-activity',
  'applications-settings': '/server/applications',
  'fwa-settings': '/server/fwa',
  'connections-settings': '/settings/integrations',
  'text-commands': '/server/commands',
  manage: '/server',
  'image-gallery': '/settings/image-gallery',
  tickets: '/tickets',
  access: '/settings/access',
  issues: '/settings/issues',
}

export function managementTarget(search: string, pathname: string): string | undefined {
  const path = pathname.replace(/\/$/, '')
  const matched = Object.entries(managementPaths).find(([, destination]) => destination === path)?.[0]
  const legacy = new URLSearchParams(search).get('view') || ''
  return matched || (pathname === '/' && Object.hasOwn(managementPaths, legacy) ? legacy : undefined)
}

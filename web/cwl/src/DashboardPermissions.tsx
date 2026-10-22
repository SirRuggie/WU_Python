import { createContext, useContext } from 'react'
export const DashboardPermissions = createContext<{ owner: boolean; permissions: string[] } | null>(null)
export function useDashboardPermission(permission: string) {
  const access = useContext(DashboardPermissions)
  return access !== null && (access.owner || access.permissions.includes(permission) || (permission.startsWith('cwl_') && access.permissions.includes('cwl')))
}

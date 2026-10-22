import { useEffect, useState } from 'react'
import { pushSupport } from './webPush'

/** Site controls can grant/revoke permission without reloading the dashboard. */
export default function usePushPermission() {
  const [support, setSupport] = useState(pushSupport)
  useEffect(() => observePushPermission(() => setSupport(pushSupport())), [])
  return { support, refreshPermission: () => setSupport(pushSupport()) }
}

export function observePushPermission(onChange: () => void) {
  let active = true
  let permission: PermissionStatus | undefined
  const refresh = () => { if (active) onChange() }
  const visible = () => { if (document.visibilityState === 'visible') refresh() }
  window.addEventListener('focus', refresh)
  window.addEventListener('pageshow', refresh)
  document.addEventListener('visibilitychange', visible)
  if (navigator.permissions?.query) {
    void navigator.permissions.query({ name: 'notifications' }).then(result => {
      if (!active) return
      permission = result
      permission.addEventListener('change', refresh)
      refresh()
    }).catch(() => { /* Unsupported permission query: focus/visibility remain available. */ })
  }
  return () => {
    active = false
    permission?.removeEventListener('change', refresh)
    window.removeEventListener('focus', refresh)
    window.removeEventListener('pageshow', refresh)
    document.removeEventListener('visibilitychange', visible)
  }
}

/** Browser plumbing only; the authenticated API owns reminder preferences. */
export type PushSupport = { supported: boolean; reason: string; permission: NotificationPermission | 'unsupported' }

export function pushSupport(): PushSupport {
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  const installed = window.matchMedia('(display-mode: standalone)').matches || !!(navigator as Navigator & { standalone?: boolean }).standalone
  if (ios && !installed) return { supported: false, reason: 'On iPhone or iPad, add this dashboard to your Home Screen and open it there to enable reminders.', permission: 'unsupported' }
  if (!window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    return { supported: false, reason: 'Push reminders need a supported browser and a secure connection. Try Chrome on Android or desktop.', permission: 'unsupported' }
  }
  return { supported: true, reason: '', permission: Notification.permission }
}

export function vapidKeyBytes(value: string): Uint8Array<ArrayBuffer> {
  const base64 = value.replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, '='))
  const bytes = new Uint8Array(raw.length)
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i)
  if (bytes.length !== 65 || bytes[0] !== 4) throw new Error('Push notification configuration is invalid.')
  return bytes
}

export async function registerPushWorker(): Promise<ServiceWorkerRegistration> {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) throw new Error('This browser does not support secure push reminders.')
  await navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' })
  // ready resolves only once an active worker can receive the subscription.
  return navigator.serviceWorker.ready
}

export async function getBrowserSubscription(): Promise<PushSubscription | null> {
  if (!pushSupport().supported) return null
  const registration = await registerPushWorker()
  return registration.pushManager.getSubscription()
}

/** Call directly from the Enable button, never during render or an effect. */
export async function enableBrowserPush(vapidPublicKey: string): Promise<PushSubscription> {
  const support = pushSupport()
  if (!support.supported) throw new Error(support.reason)
  const key = vapidKeyBytes(vapidPublicKey)
  // Request before asynchronous registration to preserve the user gesture on iOS.
  const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission()
  if (permission !== 'granted') throw new Error(permission === 'denied' ? 'Notifications are blocked. Allow them in your browser’s site settings to enable reminders.' : 'Notification permission was not granted. You can try again when ready.')
  const registration = await registerPushWorker()
  const existing = await registration.pushManager.getSubscription()
  if (existing) return existing
  return registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key })
}

export async function disableBrowserPush(): Promise<void> {
  if (!('serviceWorker' in navigator)) return
  const registration = await navigator.serviceWorker.getRegistration('/')
  const subscription = await registration?.pushManager.getSubscription()
  if (subscription && !(await subscription.unsubscribe())) throw new Error('Could not disable notifications on this device. Please try again.')
  const notifications = await registration?.getNotifications()
  notifications?.forEach(notification => notification.close())
}

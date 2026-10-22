/** Browser plumbing only; the authenticated API owns reminder preferences. */
export class PushPermissionError extends Error {
  constructor(public readonly permission: 'default' | 'denied') {
    super(permission === 'denied'
      ? 'Notifications are blocked for this site. Allow them in your browser settings, then recheck permission.'
      : 'The browser did not grant permission. If no prompt appeared, open this page in your full browser and check its notification settings.')
    this.name = 'PushPermissionError'
  }
}

export function pushPlatform(): 'ios' | 'android' | 'desktop' {
  if (/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)) return 'ios'
  return /Android/i.test(navigator.userAgent) ? 'android' : 'desktop'
}

async function workerReady(): Promise<ServiceWorkerRegistration> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      navigator.serviceWorker.ready,
      new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Notification setup took too long. Check your connection and try enabling again.')), 12000) }),
    ])
  } finally { clearTimeout(timer) }
}
export type PushSupport = { supported: boolean; reason: string; permission: NotificationPermission | 'unsupported' }

export function pushSupport(): PushSupport {
  const ios = pushPlatform() === 'ios'
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
  return workerReady()
}

export async function getBrowserSubscription(): Promise<PushSubscription | null> {
  if (!pushSupport().supported || Notification.permission !== 'granted') return null
  const registration = await registerPushWorker()
  return registration.pushManager.getSubscription()
}

/** Call directly from the Enable button, never during render or an effect. */
export async function enableBrowserPush(vapidPublicKey: string): Promise<PushSubscription> {
  const support = pushSupport()
  if (!support.supported) throw new Error(support.reason)
  if (support.permission === 'denied') throw new PushPermissionError('denied')
  const key = vapidKeyBytes(vapidPublicKey)
  // Request before asynchronous registration to preserve the user gesture on iOS.
  const permission = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission()
  if (permission !== 'granted') throw new PushPermissionError(permission === 'denied' ? 'denied' : 'default')
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

export async function subscriptionId(subscription: PushSubscription): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(subscription.endpoint))
  return [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('')
}

// End this browser's personal reminders before ending the authenticated session.
export async function stopPushOnSignout(): Promise<string | null> {
  let id: string | null = null
  try {
    const registration = 'serviceWorker' in navigator ? await navigator.serviceWorker.getRegistration('/') : null
    const subscription = await registration?.pushManager?.getSubscription()
    if (subscription) id = await subscriptionId(subscription)
  } catch {
    // A missing subscription ID should not prevent the unsubscribe attempt.
  }
  try {
    await disableBrowserPush()
  } catch {
    // Browser failures must not block ending the authenticated session.
  }
  return id
}

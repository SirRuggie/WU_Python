import { afterEach, expect, it, vi } from 'vitest'
import { disableBrowserPush, enableBrowserPush, pushSupport, stopPushOnSignout, vapidKeyBytes } from './webPush'

afterEach(() => vi.unstubAllGlobals())
const publicKey = btoa(String.fromCharCode(4) + 'x'.repeat(64)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
function browser(permission: NotificationPermission = 'default') {
  const subscribe = vi.fn().mockResolvedValue({ endpoint: 'https://push.example.test/abc' })
  const getSubscription = vi.fn().mockResolvedValue(null)
  const registration = { pushManager: { subscribe, getSubscription }, getNotifications: vi.fn().mockResolvedValue([]) }
  const register = vi.fn().mockResolvedValue(registration)
  vi.stubGlobal('navigator', { userAgent: 'Chrome', platform: 'Linux', maxTouchPoints: 0, serviceWorker: { register, ready: Promise.resolve(registration), getRegistration: vi.fn().mockResolvedValue(registration) } })
  vi.stubGlobal('window', { isSecureContext: true, matchMedia: () => ({matches: false}), Notification: {}, PushManager: {} })
  const requestPermission = vi.fn().mockResolvedValue('granted')
  vi.stubGlobal('Notification', { permission, requestPermission })
  return { subscribe, getSubscription, requestPermission, register, registration }
}
it('decodes URL-safe VAPID keys and rejects invalid key length', () => {
  expect(vapidKeyBytes(publicKey)).toHaveLength(65)
  expect(vapidKeyBytes(publicKey)[0]).toBe(4)
  expect(() => vapidKeyBytes('YWJj')).toThrow('configuration')
})
it('checking support never prompts; iOS outside the installed app has clear guidance', () => {
  const b = browser()
  expect(pushSupport().supported).toBe(true)
  expect(b.requestPermission).not.toHaveBeenCalled()
  vi.stubGlobal('navigator', {userAgent:'iPhone',platform:'iPhone',maxTouchPoints:1})
  expect(pushSupport().reason).toContain('Home Screen')
})
it('subscribes only after permission and reuses an existing subscription', async () => {
  const b = browser()
  const old = { endpoint: 'https://push.example.test/existing' }
  b.getSubscription.mockResolvedValue(old)
  expect(await enableBrowserPush(publicKey)).toBe(old)
  expect(b.requestPermission).toHaveBeenCalledOnce()
  expect(b.subscribe).not.toHaveBeenCalled()
})
it('refuses denied permission and never registers a subscription', async () => {
  const b = browser('denied')
  b.requestPermission.mockResolvedValue('denied')
  await expect(enableBrowserPush(publicKey)).rejects.toThrow('blocked')
  expect(b.subscribe).not.toHaveBeenCalled()
  expect(b.register).not.toHaveBeenCalled()
})
it('unsubscribe closes visible notifications on this device', async () => {
  const b = browser('granted')
  const unsubscribe = vi.fn().mockResolvedValue(true)
  const close = vi.fn()
  b.getSubscription.mockResolvedValue({ unsubscribe })
  b.registration.getNotifications.mockResolvedValue([{ close }])
  await disableBrowserPush()
  expect(unsubscribe).toHaveBeenCalledOnce()
  expect(close).toHaveBeenCalledOnce()
})

it('identifies and unsubscribes this browser before sign-out', async () => {
  const b = browser('granted')
  const unsubscribe = vi.fn().mockResolvedValue(true)
  b.getSubscription.mockResolvedValue({ endpoint: 'https://push.example.test/abc', unsubscribe })
  const id = await stopPushOnSignout()
  expect(id).toMatch(/^[0-9a-f]{64}$/)
  expect(unsubscribe).toHaveBeenCalledOnce()
})

it('still attempts unsubscribe when subscription fingerprinting fails', async () => {
  const b = browser('granted')
  const unsubscribe = vi.fn().mockResolvedValue(true)
  b.getSubscription.mockResolvedValue({ endpoint: 'https://push.example.test/abc', unsubscribe })
  vi.stubGlobal('crypto', { subtle: { digest: vi.fn().mockRejectedValue(new Error('unavailable')) } })
  expect(await stopPushOnSignout()).toBeNull()
  expect(unsubscribe).toHaveBeenCalledOnce()
})

it('requests permission synchronously before worker setup, without an intervening fetch', async () => {
  const b = browser()
  const pending = enableBrowserPush(publicKey)
  expect(b.requestPermission).toHaveBeenCalledOnce()
  expect(b.register).not.toHaveBeenCalled()
  await pending
  expect(b.subscribe).toHaveBeenCalledOnce()
})
it('an undecided or expired prompt is distinct from a browser block', async () => {
  const b = browser()
  b.requestPermission.mockResolvedValue('default')
  await expect(enableBrowserPush(publicKey)).rejects.toMatchObject({ name: 'PushPermissionError', permission: 'default' })
  expect(b.register).not.toHaveBeenCalled()
  expect(b.subscribe).not.toHaveBeenCalled()
})
it('never prompts repeatedly when the browser has blocked permission', async () => {
  const b = browser('denied')
  await expect(enableBrowserPush(publicKey)).rejects.toMatchObject({ permission: 'denied' })
  expect(b.requestPermission).not.toHaveBeenCalled()
})
it('does not prompt again after permission was allowed through site controls', async () => {
  const b = browser('granted')
  await enableBrowserPush(publicKey)
  expect(b.requestPermission).not.toHaveBeenCalled()
  expect(b.subscribe).toHaveBeenCalledWith({ userVisibleOnly: true, applicationServerKey: expect.any(Uint8Array) })
})
it('does not leave setup working forever when the service worker cannot activate', async () => {
  vi.useFakeTimers()
  try {
    browser('granted')
    Object.defineProperty(navigator.serviceWorker, 'ready', { value: new Promise(() => {}) })
    const pending = expect(enableBrowserPush(publicKey)).rejects.toThrow('took too long')
    await vi.advanceTimersByTimeAsync(12000)
    await pending
  } finally { vi.useRealTimers() }
})

it('supports Android browser tabs without requiring installation', () => {
  browser()
  Object.defineProperty(navigator, 'userAgent', { value: 'Mozilla/5.0 (Linux; Android 15) Chrome/155.0' })
  expect(pushSupport().supported).toBe(true)
})
it('does not treat an embedded browser without PushManager as supported', () => {
  browser()
  delete (window as unknown as Record<string, unknown>).PushManager
  expect(pushSupport().supported).toBe(false)
})

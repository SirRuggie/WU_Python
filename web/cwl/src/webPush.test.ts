import { afterEach, expect, it, vi } from 'vitest'
import { disableBrowserPush, enableBrowserPush, pushSupport, vapidKeyBytes } from './webPush'

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

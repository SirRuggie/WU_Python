import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { expect, it, vi } from 'vitest'
const source = readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8')
function worker() {
  const handlers = {}
  const showNotification = vi.fn().mockResolvedValue(undefined)
  const openWindow = vi.fn().mockResolvedValue(undefined)
  runInNewContext(source, { URL, self: { location: { origin: 'https://cwl.example.test' }, addEventListener: (type,fn) => { handlers[type] = fn }, registration: { showNotification }, clients: { matchAll: async () => [], openWindow } } })
  return { handlers, showNotification, openWindow }
}
it('does not intercept authenticated requests or cache private data', () => {
  expect(worker().handlers.fetch).toBeUndefined()
})
it('displays push payload while fixing hostile URLs to same-origin Todo', async () => {
  const w = worker()
  let completion
  w.handlers.push({ data: { json: () => ({ title: 'War ends soon', body: '2 accounts need attacks', url:'https://bad.example/phish', tag:'clan1' }) }, waitUntil: p => { completion = p } })
  await completion
  expect(w.showNotification).toHaveBeenCalledWith('War ends soon', expect.objectContaining({body:'2 accounts need attacks',tag:'clan1',data:{url:'https://cwl.example.test/?view=todo'}}))
})
it('malformed payload still produces a visible fallback', async () => {
  const w=worker()
  let completion
  w.handlers.push({data:{json:()=>{throw new Error('bad')}},waitUntil:p=>{completion=p}})
  await completion
  expect(w.showNotification).toHaveBeenCalledWith('Warriors United reminder', expect.anything())
})
it('notification click cannot navigate to an external origin', async () => {
  const w=worker()
  let completion
  const close=vi.fn()
  w.handlers.notificationclick({notification:{close,data:{url:'https://bad.example/'}},waitUntil:p=>{completion=p}})
  await completion
  expect(close).toHaveBeenCalledOnce()
  expect(w.openWindow).toHaveBeenCalledWith('https://cwl.example.test/?view=todo')
})

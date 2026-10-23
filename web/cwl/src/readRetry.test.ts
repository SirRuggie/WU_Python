import { afterEach, expect, it, vi } from 'vitest'
import { fetchReadWithRetry } from './readRetry'
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
it('recovers transient reads and stops after three attempts', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn().mockResolvedValueOnce(new Response('', {status:503})).mockRejectedValueOnce(new TypeError('offline')).mockResolvedValue(new Response('{}'))
  vi.stubGlobal('fetch', fetch)
  const result = fetchReadWithRetry('/test'); await vi.runAllTimersAsync()
  expect((await result).status).toBe(200); expect(fetch).toHaveBeenCalledTimes(3)
})
it('returns the last failure after bounded attempts', async () => {
  vi.useFakeTimers(); const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('', {status:502}))); vi.stubGlobal('fetch',fetch)
  const result = fetchReadWithRetry('/test'); await vi.runAllTimersAsync()
  expect((await result).status).toBe(502); expect(fetch).toHaveBeenCalledTimes(3)
})
it.each(['POST','PATCH','DELETE','PUT'])('never retries %s', async method => {
  const fetch = vi.fn().mockResolvedValue(new Response('', {status:503})); vi.stubGlobal('fetch',fetch)
  await fetchReadWithRetry('/test',{method}); expect(fetch).toHaveBeenCalledTimes(1)
})
it.each([400,401,403,404,409,423,429])('does not retry status %s', async status => {
  const fetch = vi.fn().mockResolvedValue(new Response('', {status})); vi.stubGlobal('fetch',fetch)
  await fetchReadWithRetry('/test'); expect(fetch).toHaveBeenCalledTimes(1)
})
it('does not multiply exhausted upstream retries', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response('', {status:503,headers:{'X-Read-Retries-Exhausted':'1'}})); vi.stubGlobal('fetch',fetch)
  await fetchReadWithRetry('/test'); expect(fetch).toHaveBeenCalledTimes(1)
})
it('does not retry cancellation or network errors on writes', async () => {
  const fetch = vi.fn().mockRejectedValue(new DOMException('Canceled','AbortError')); vi.stubGlobal('fetch',fetch)
  await expect(fetchReadWithRetry('/test')).rejects.toThrow('Canceled'); expect(fetch).toHaveBeenCalledTimes(1)
  fetch.mockRejectedValue(new TypeError('offline'))
  await expect(fetchReadWithRetry('/test',{method:'POST'})).rejects.toThrow('offline'); expect(fetch).toHaveBeenCalledTimes(2)
})

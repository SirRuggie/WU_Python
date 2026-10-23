// Only safe reads may repeat. Writes and uncertain deliveries get one attempt.
export async function fetchReadWithRetry(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const read = (init.method ?? 'GET').toUpperCase() === 'GET'
  for (let attempt = 0; ; attempt++) {
    try {
      const response = await fetch(input, init)
      if (!read || attempt >= 2 || ![500, 502, 503, 504].includes(response.status)
        || response.headers.get('X-Read-Retries-Exhausted') === '1') return response
      // Release the failed response before the next attempt.
      await response.body?.cancel().catch(() => undefined)
    } catch (error) {
      if (!read || attempt >= 2 || init.signal?.aborted
        || (error instanceof Error && error.name === 'AbortError')) throw error
    }
    await new Promise<void>(resolve => setTimeout(resolve, [400, 1000][attempt]))
    if (init.signal?.aborted) throw new DOMException('Request canceled', 'AbortError')
  }
}

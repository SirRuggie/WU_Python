// Only safe reads may repeat. Writes and uncertain deliveries get one attempt.
export async function fetchReadWithRetry(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const read = (init.method ?? 'GET').toUpperCase() === 'GET'
  for (let attempt = 0; ; attempt++) {
    let gatewayFailure = false
    try {
      const response = await fetch(input, init)
      if (!read || attempt >= 2 || ![500, 502, 503, 504].includes(response.status)
        || response.headers.get('X-Read-Retries-Exhausted') === '1') return response
      gatewayFailure = [502, 504].includes(response.status)
      // Release the failed response before the next attempt.
      await response.body?.cancel().catch(() => undefined)
    } catch (error) {
      gatewayFailure = true
      if (!read || attempt >= 2 || init.signal?.aborted
        || (error instanceof Error && error.name === 'AbortError')) throw error
    }
    // Gateway recovery needs time for the service to drain and start again.
    // Keep the attempt limit; do not rapidly exhaust it during a brief restart.
    const delay = gatewayFailure ? [1500, 10000][attempt] : [400, 1000][attempt]
    await new Promise<void>(resolve => setTimeout(resolve, delay))
    if (init.signal?.aborted) throw new DOMException('Request canceled', 'AbortError')
  }
}

export class StrikeImportFailed extends Error {}

export type StrikeImportJob<T> = {
  job_id: string
  status: 'running' | 'complete' | 'failed'
  result?: T
  error?: string
}

export function isStrikeImportJob(value: unknown): value is StrikeImportJob<unknown> {
  return !!value && typeof value === 'object' && typeof (value as { job_id?: unknown }).job_id === 'string'
}

export function nextStrikePoll(signal: AbortSignal, delay = 2000): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) { reject(new DOMException('Cancelled', 'AbortError')); return }
    const timer = setTimeout(() => { signal.removeEventListener('abort', cancel); resolve() }, delay)
    const cancel = () => { clearTimeout(timer); signal.removeEventListener('abort', cancel); reject(new DOMException('Cancelled', 'AbortError')) }
    signal.addEventListener('abort', cancel, { once: true })
  })
}

export async function waitForStrikeImport<T>(
  jobId: string,
  fetchJob: (jobId: string) => Promise<StrikeImportJob<T>>,
  signal: AbortSignal,
  pause: (signal: AbortSignal) => Promise<void> = nextStrikePoll,
): Promise<T> {
  let fetchFailures = 0
  while (!signal.aborted) {
    let job: StrikeImportJob<T>
    try { job = await fetchJob(jobId); fetchFailures = 0 }
    catch (error) {
      if (signal.aborted) break
      if (++fetchFailures >= 3) throw error
      await pause(signal)
      continue
    }
    if (signal.aborted) break
    if (job.status === 'failed') throw new StrikeImportFailed(job.error || 'Import failed. Try again.')
    if (job.status === 'complete') {
      if (job.result === undefined) throw new Error('Import finished without a result. Refresh and try again.')
      return job.result
    }
    await pause(signal)
  }
  throw new DOMException('Cancelled', 'AbortError')
}

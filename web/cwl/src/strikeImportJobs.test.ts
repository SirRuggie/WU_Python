import { expect, it } from 'vitest'
import { isStrikeImportJob, waitForStrikeImport, type StrikeImportJob } from './strikeImportJobs'

it('accepts a background job and returns its completed result after polling', async () => {
  const states: StrikeImportJob<{ preview_id: string }>[] = [
    { job_id: 'job-1', status: 'running' },
    { job_id: 'job-1', status: 'complete', result: { preview_id: 'preview-1' } },
  ]
  let reads = 0
  const result = await waitForStrikeImport('job-1', async () => states[reads++], new AbortController().signal, async () => {})
  expect(result).toEqual({ preview_id: 'preview-1' })
  expect(reads).toBe(2)
  expect(isStrikeImportJob({ job_id: 'job-1', status: 'running' })).toBe(true)
})

it('surfaces a failed job without retrying indefinitely', async () => {
  await expect(waitForStrikeImport('job-2', async () => ({ job_id: 'job-2', status: 'failed', error: 'History unavailable' }), new AbortController().signal, async () => {})).rejects.toThrow('History unavailable')
})

it('stops polling after the page leaves', async () => {
  const controller = new AbortController()
  controller.abort()
  let reads = 0
  await expect(waitForStrikeImport('job-3', async () => { reads++; return { job_id: 'job-3', status: 'running' } }, controller.signal, async () => {})).rejects.toMatchObject({ name: 'AbortError' })
  expect(reads).toBe(0)
})

it('retries brief status request failures before completing', async () => {
  let reads = 0
  const result = await waitForStrikeImport('job-4', async () => {
    reads++
    if (reads < 3) throw new Error('Temporary connection error')
    return { job_id: 'job-4', status: 'complete', result: { applied: 1 } }
  }, new AbortController().signal, async () => {})
  expect(result).toEqual({ applied: 1 })
  expect(reads).toBe(3)
})

it('stops after three consecutive status request failures', async () => {
  let reads = 0
  await expect(waitForStrikeImport('job-5', async () => { reads++; throw new Error('Temporary connection error') }, new AbortController().signal, async () => {})).rejects.toThrow('Temporary connection error')
  expect(reads).toBe(3)
})

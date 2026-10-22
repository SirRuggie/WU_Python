import { expect, it } from 'vitest'
import { rosterAccountPages } from './rosterGrouping'
import type { RosterAccount } from './roster'
const account = (tag: string, user_id: string) => ({ tag, user_id } as RosterAccount)

it('keeps the normal list order and twenty-account pages when grouping is off', () => {
  const rows = Array.from({ length: 45 }, (_, i) => account(`#${i}`, String(i % 3)))
  const pages = rosterAccountPages(rows, false)
  expect(pages.map(page => page.length)).toEqual([20, 20, 5])
  expect(pages.flat()).toEqual(rows)
})
it('groups by exact Discord ID while preserving account sort within each member', () => {
  const rows = [account('#A', '111'), account('#B', '222'), account('#C', '111')]
  expect(rosterAccountPages(rows, true).flat().map(row => row.tag)).toEqual(['#A', '#C', '#B'])
  expect(rows.map(row => row.tag)).toEqual(['#A', '#B', '#C'])
})
it('does not merge unrelated unlinked accounts', () => {
  const rows = [account('#A', ''), account('#B', '1'), account('#C', '')]
  expect(rosterAccountPages(rows, true).flat()).toEqual(rows)
})
it('never splits a member across pages or drops an oversized group', () => {
  const rows = [
    ...Array.from({ length: 18 }, (_, i) => account(`#A${i}`, '1')),
    ...Array.from({ length: 3 }, (_, i) => account(`#B${i}`, '2')),
    ...Array.from({ length: 51 }, (_, i) => account(`#C${i}`, '3')),
    account('#D', '4'),
  ]
  const pages = rosterAccountPages(rows, true)
  expect(pages.map(page => page.length)).toEqual([18, 3, 51, 1])
  expect(pages.flat()).toEqual(rows)
  expect(rosterAccountPages([], true)).toEqual([])
})

import { expect, it } from 'vitest'
import { defaultLeaveTags, selectedImportEntries, toggleLeaveTag } from './strikeSelections'

it('imports record-only missed attacks even when there are no strikes', () => {
  const entries = [
    { key: 'one-missed', will_strike: false },
    { key: 'old-strike', will_strike: true, duplicate: true },
    { key: 'exempt', will_strike: true, exempt: true },
  ]
  expect(selectedImportEntries(entries, []).map(item => item.key)).toEqual(['one-missed', 'exempt'])
  expect(selectedImportEntries(entries, ['one-missed']).map(item => item.key)).toEqual(['exempt'])
})

it('selects every linked account for leave and allows one exception', () => {
  const tags = defaultLeaveTags([{ tag: '#ONE' }, { tag: '#TWO' }, { tag: '#THREE' }])
  expect(tags).toEqual(['#ONE', '#TWO', '#THREE'])
  expect(toggleLeaveTag(tags, '#TWO', false)).toEqual(['#ONE', '#THREE'])
  expect(toggleLeaveTag(tags, '#TWO', true)).toEqual(tags)
})

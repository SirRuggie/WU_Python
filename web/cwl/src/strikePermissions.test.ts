import { expect, it } from 'vitest'
import { strikePermissions } from './strikePermissions'

it('keeps adding and removing independent from strike settings access', () => {
  expect(strikePermissions(['strikes'])).toEqual({ view: true, manage: true, add: false, remove: false })
  expect(strikePermissions(['strikes_add'])).toEqual({ view: true, manage: false, add: true, remove: false })
  expect(strikePermissions(['strikes_remove'])).toEqual({ view: true, manage: false, add: false, remove: true })
  expect(strikePermissions(['strikes_add', 'strikes_remove'])).toEqual({ view: true, manage: false, add: true, remove: true })
  expect(strikePermissions([], true)).toEqual({ view: true, manage: true, add: true, remove: true })
})

import {describe,it,expect} from 'vitest'
import {imageCategory} from './imageCategories'
describe('gallery categories',()=>{
 it('groups nested clan and FWA paths into broad categories',()=>{
  expect(imageCategory('clans/Warriors_United')).toBe('Clans')
  expect(imageCategory('clans/Arcane_Oasis')).toBe('Clans')
  expect(imageCategory('fwa/bases/th18_new')).toBe('FWA')
  expect(imageCategory('fwa/static')).toBe('FWA')
 })
 it('groups existing aliases and content without exposing storage paths',()=>{
  expect(imageCategory('Clan Images')).toBe('Clans')
  for(const value of ['Banners','Logos','branding/banners'])expect(imageCategory(value)).toBe('Branding')
  expect(imageCategory('recruit/strikes')).toBe('Recruitment')
  expect(imageCategory('content/command-triggers/123')).toBe('Triggers')
  expect(imageCategory('tickets/static')).toBe('Tickets')
 })
 it('keeps custom top-level categories and unsorted images',()=>{
  expect(imageCategory('Events/2026')).toBe('Events')
  expect(imageCategory('')).toBe('')
  expect(imageCategory()).toBe('')
 })
})

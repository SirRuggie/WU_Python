import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ClanDirectory from './ClanDirectory'

const clan = { tag: '#P0LY', name: 'Edrag Rush', type: 'Main', logo: '' }
const defaults = { clans: [clan], types: ['Main'], selected: null, query: '', onQuery: () => {}, clanType: '', onType: () => {}, expanded: false, onExpanded: () => {}, disabled: false, loading: false, error: '', onRetry: () => {}, onSelect: () => {} }

describe('Clan directory recovery and filtering', () => {
  it('does not report an empty family while loading', () => {
    const html = renderToStaticMarkup(<ClanDirectory {...defaults} clans={[]} loading />)
    expect(html).toContain('Loading clans')
    expect(html).not.toContain('No family clans')
    expect(html).not.toContain('No clans match')
  })
  it('offers recovery rather than reporting failed data as empty', () => {
    const html = renderToStaticMarkup(<ClanDirectory {...defaults} clans={[]} error="Connection lost" />)
    expect(html).toContain('Connection lost')
    expect(html).toContain('Retry')
    expect(html).not.toContain('No family clans')
  })
  it('distinguishes an empty family from filters without matches', () => {
    expect(renderToStaticMarkup(<ClanDirectory {...defaults} clans={[]} />)).toContain('Add a clan by tag')
    const html = renderToStaticMarkup(<ClanDirectory {...defaults} query="missing" />)
    expect(html).toContain('No clans match these filters')
    expect(html).toContain('Clear filters')
  })
  it('accepts pasted names with surrounding whitespace and matches tags', () => {
    expect(renderToStaticMarkup(<ClanDirectory {...defaults} query=" EDRAG " />)).toContain('<strong>Edrag Rush</strong>')
    expect(renderToStaticMarkup(<ClanDirectory {...defaults} query="#p0ly" />)).toContain('<strong>Edrag Rush</strong>')
  })
  it('keeps the mobile selector and clan choices disabled during mutations', () => {
    const html = renderToStaticMarkup(<ClanDirectory {...defaults} selected={clan} disabled />)
    expect((html.match(/disabled=""/g) || []).length).toBe(2)
  })
})

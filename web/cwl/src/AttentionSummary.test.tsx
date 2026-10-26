import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import AttentionSummary from './AttentionSummary'

describe('AttentionSummary', () => {
  it('renders a visible recovery action and escapes external text', () => {
    const html = renderToStaticMarkup(createElement(AttentionSummary, {
      items: [{ title: 'Read failed', detail: '<script>bad</script>', action: { label: 'Refresh', onClick: () => {} }, technicalDetail: 'request <failed>' }],
      urgent: true,
    }))
    expect(html).toContain('role="alert"')
    expect(html).toContain('>Refresh</button>')
    expect(html).toContain('&lt;script&gt;bad&lt;/script&gt;')
    expect(html).toContain('Technical details')
    expect(html).not.toContain('<script>')
  })

  it('labels affected-account details plainly', () => {
    const html = renderToStaticMarkup(createElement(AttentionSummary, {items: [{title: 'Links need checking', technicalDetail: '<Player> · #TAG', detailsLabel: 'Accounts to check'}]}))
    expect(html).toContain('Accounts to check')
    expect(html).toContain('&lt;Player&gt;')
    expect(html).not.toContain('Technical details')
  })

  it('renders nothing when no attention is needed', () => {
    expect(renderToStaticMarkup(createElement(AttentionSummary, { items: [] }))).toBe('')
  })
})

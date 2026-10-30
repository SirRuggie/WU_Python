import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import ModerationPreviewCard from './ModerationPreviewCard'

it('renders component text safely and allows only Discord profile links', () => {
  const html = renderToStaticMarkup(createElement(ModerationPreviewCard, {
    payload: {
      flags: 32768,
      components: [{ type: 17, accent_color: 15112501, components: [
        { type: 10, content: '### 👢 Member kicked' },
        { type: 10, content: '**Reason**\n<script>alert(1)</script>' },
        { type: 1, components: [
          { type: 2, label: 'View profile', url: 'https://discord.com/users/123456789' },
          { type: 2, label: 'Unsafe', url: 'javascript:alert(1)' },
        ] },
      ] }],
    },
  }))
  expect(html).toContain('Member kicked')
  expect(html).toContain('&lt;script&gt;alert(1)&lt;/script&gt;')
  expect(html).toContain('href="https://discord.com/users/123456789"')
  expect(html).not.toContain('href="javascript:')
})

it('renders the forum embed payload separately', () => {
  const html = renderToStaticMarkup(createElement(ModerationPreviewCard, {
    forum: true,
    payload: { embeds: [{ description: 'Forum starter', color: 15112501 }] },
  }))
  expect(html).toContain('Forum starter')
  expect(html).toContain('Forum starter preview')
})

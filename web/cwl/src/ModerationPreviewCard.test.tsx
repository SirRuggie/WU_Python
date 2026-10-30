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
        { type: 10, content: '**Reason**\n<script>alert(1)</script> · <@123456789> · <t:1717243200:f>' },
        { type: 9, components: [{ type: 10, content: '**Example Member**' }], accessory: { type: 11, media: { url: 'https://cdn.discordapp.com/embed/avatars/0.png' } } },
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
  expect(html).toContain('@123456789')
  expect(html).toContain('dateTime="2024-06-01T12:00:00.000Z"')
  expect(html).toContain('Sample member avatar')
})

it('renders the forum embed payload separately', () => {
  const html = renderToStaticMarkup(createElement(ModerationPreviewCard, {
    forum: true,
    payload: { embeds: [{ description: 'Forum starter for <@123456789>\n**Reason**: <script>', color: 15112501, thumbnail: { url: 'https://cdn.discordapp.com/embed/avatars/0.png' } }] },
  }))
  expect(html).toContain('Forum starter')
  expect(html).toContain('Forum starter preview')
  expect(html).toContain('@123456789')
  expect(html).toContain('&lt;script&gt;')
})

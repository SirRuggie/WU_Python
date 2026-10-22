import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import AccessAvatar from './AccessAvatar'
it('renders Discord pictures without making role identities look like users', () => {
  expect(renderToStaticMarkup(<AccessAvatar name="Staff" kind="user" url="https://cdn.discordapp.com/avatars/1/avatar.png" />)).toContain('<img')
  expect(renderToStaticMarkup(<AccessAvatar name="Staff" kind="role" url="https://cdn.discordapp.com/avatars/1/avatar.png" />)).not.toContain('<img')
  expect(renderToStaticMarkup(<AccessAvatar name="Staff" kind="user" url="https://other.test/avatar.png" />)).not.toContain('<img')
  expect(renderToStaticMarkup(<AccessAvatar name="Staff" kind="user" />)).toContain('>S</span>')
})

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import DashboardIssues, { matchesIssue, type Issue } from './DashboardIssues'
import DiscordIdentity from './DiscordIdentity'
import type { MemberOption } from './MemberPicker'
const issue: Issue = { id: 'abc123', at: 1, member: '123456789012345678', kind: 'server_error', status: 500, action: '/api/cwl/roster', method: 'GET' }
const profile: MemberOption = { id: issue.member!, value: issue.member!, label: 'Tester', display_name: '<Tester>', username: 'discord_name', avatar_url: 'https://cdn.discordapp.com/avatars/test.png', role_ids: [] }
describe('readable issue history', () => {
  it('finds names, usernames, IDs and references without case sensitivity', () => {
    for (const search of ['<TESTER>', 'DISCORD_NAME', issue.member!, 'ABC123', 'roster']) {
      expect(matchesIssue(issue, { [profile.id]: profile }, search, '')).toBe(true)
    }
    expect(matchesIssue(issue, {}, 'abc', 'network_error')).toBe(false)
    expect(matchesIssue(issue, {}, issue.member!, '')).toBe(true)
  })
  it('renders supplied Discord identity safely without an additional lookup', () => {
    const html = renderToStaticMarkup(<DiscordIdentity userId={profile.id} resolvedMember={profile} />)
    expect(html).toContain('&lt;Tester&gt;')
    expect(html).toContain('@discord_name')
    expect(html).not.toContain('Discord ID:')
    expect(html).toContain('cdn.discordapp.com/avatars/test.png')
    expect(html).not.toContain('Loading Discord')
  })
  it('provides labeled search, filters, loading and secondary history', () => {
    const html = renderToStaticMarkup(<DashboardIssues />)
    expect(html).toContain('Find an issue')
    expect(html).toContain('Issue type')
    expect(html).toContain('Loading reports…')
    expect(html).toContain('About this history')
  })
})

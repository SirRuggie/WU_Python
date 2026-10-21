import {reminderPreviewText} from './warReminderPreview'
import {describe,expect,it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import DiscordPreview,{DiscordText,discordMarkdown,previewUrl,type PreviewPart} from './DiscordPreview'

describe('Discord preview content safety',()=>{
 it('renders Markdown formatting without active HTML or clickable links',()=>{
  const html=renderToStaticMarkup(<DiscordText text={'**Hello**\n\n<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[Click](javascript:alert(1)) [Safe](https://example.com)'} />)
  expect(html).toContain('<strong>Hello</strong>')
  expect(html).not.toMatch(/<script|onerror=|<a\b|href=/i)
  expect(html).toContain('discord-preview-link')
 })
 it('keeps preview buttons and selectors inert even with hostile values',()=>{
  const parts:PreviewPart[]=[{type:'row',children:[{type:'button',label:'<script>send()</script>',url:'javascript:send()',style:'primary" onclick="send()'},{type:'select',placeholder:'Choose a clan',options:[{label:'A'}]}]}]
  const html=renderToStaticMarkup(<DiscordPreview parts={parts}/>)
  expect(html).not.toMatch(/<button|<select|<a\b|href=|<script| onclick="/)
  expect(html).toContain('&lt;script&gt;send()&lt;/script&gt;')
  expect(html).toContain('Preview buttons do not send or open anything.')
 })
 it('blocks executable and private URLs while preserving approved artwork paths',()=>{
  for(const value of ['javascript:alert(1)','data:image/svg+xml,<svg onload=alert(1)>','http://example.com/a.png','https://user:pass@example.com/a','https://127.0.0.1/a','https://10.1.2.3/a','https://172.20.1.1/a','https://192.168.2.1/a','https://[::1]/a','https://host.internal/a','https://foo.local./a','https://0.0.0.0/a','https://100.64.0.1/a','https://8.8.8.8/a','//evil.test/a','/api/cwl/manage/content/recruit/artwork/../private'])expect(previewUrl(value),value).toBeUndefined()
  expect(previewUrl('/api/cwl/manage/content/recruit/artwork/ab1234')).toBe('/api/cwl/manage/content/recruit/artwork/ab1234')
 })
 it('replaces unsafe images with placeholders and suppresses referrers on safe images',()=>{
  const html=renderToStaticMarkup(<DiscordPreview parts={[{type:'media',items:[{url:'javascript:alert(1)',description:'Blocked image'},{url:'https://cdn.discordapp.com/attachments/123/456/a.png',description:'Clan logo'}]}]}/>)
  expect(html).not.toContain('javascript:')
  expect(html).toContain('discord-image-placeholder')
  expect(html).toContain('referrerPolicy="no-referrer"')
  expect(html).toContain('alt="Clan logo"')
 })
 it('shows custom emoji and human-readable mentions without pinging',()=>{
  const text=discordMarkdown('<:townhall:123> <a:spin:456> <@123> <@&456> <#789>')
  expect(text).toContain('https://cdn.discordapp.com/emojis/123.png')
  expect(text).toContain('https://cdn.discordapp.com/emojis/456.gif')
  const html=renderToStaticMarkup(<DiscordText text={text}/>)
  expect(html).toContain('@member 123');expect(html).toContain('@role 456');expect(html).toContain('#channel 789')
  expect(html).toContain('discord-emoji')
  expect(html).not.toMatch(/<a\b|href=/)
 })
})

 it('keeps compact reminder owners outside the preceding account quote',()=>{
  const html=renderToStaticMarkup(<DiscordText text={reminderPreviewText('<@123>\n> **Account one** `#ONE` · 0/2\n<@456>\n> **Account two** `#TWO` · 1/2\n**Unlinked accounts**\n> **Account three** `#THREE` · 0/2')} />)
  expect(html.match(/<blockquote>/g)).toHaveLength(3)
  for(const quote of html.match(/<blockquote>[\s\S]*?<\/blockquote>/g)||[]) {
   expect(quote).not.toContain('@member')
   expect(quote).not.toContain('Unlinked accounts')
  }
 })

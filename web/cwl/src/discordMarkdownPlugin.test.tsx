import {expect,it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import Preview,{DiscordText} from './DiscordPreview'
it('renders Discord footer text, underline and protected spoilers',()=>{
 const html=renderToStaticMarkup(<DiscordText text={'-# Small footer\n\n__underlined__ and ||hidden||'}/>)
 expect(html).toContain('discord-subtext');expect(html).toContain('<u>underlined</u>');expect(html).toContain('Show spoiler');expect(html).not.toContain('hidden')
})
it('keeps code literal and never renders raw HTML',()=>{
 const html=renderToStaticMarkup(<DiscordText text={'`||code||`\n\n<script>alert(1)</script>'}/>)
 expect(html).toContain('||code||');expect(html).not.toContain('<script>')
})
it('previews video controls, dropdown choices and uploaded files',()=>{
 const html=renderToStaticMarkup(<Preview parts={[{type:'media',items:[{url:'https://example.com/a.mp4',description:'Video'}]},{type:'select',placeholder:'Choose',options:[{label:'Help'}]},{type:'file',label:'guide.pdf',size:1024}]}/>)
 expect(html).toContain('<video');expect(html).toContain('preload="none"');expect(html).toContain('Help');expect(html).toContain('guide.pdf');expect(html).toContain('1.0 KB')
})

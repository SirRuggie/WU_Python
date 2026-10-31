import {expect,it} from 'vitest'
import {renderToStaticMarkup} from 'react-dom/server'
import ChangeHistory,{supportsHistory} from './ChangeHistory'
it('offers history only for restorable configuration editors',()=>{
 for(const path of ['/manage/content/war--win','/manage/operations/fwa_weight/18','/manage/ticket-settings/timers','/manage/text-commands/%21cwl'])expect(supportsHistory(path)).toBe(true)
 for(const path of ['/manage/roles','/manage/ticket-settings/tools','/manage/operations/fwa_weight/new'])expect(supportsHistory(path)).toBe(false)
})
it('keeps history collapsed and explains that restore does not publish',()=>{
 const html=renderToStaticMarkup(<ChangeHistory target="/manage/content/war--win" revision={1} disabled={false} onBusy={()=>{}} onRestored={async()=>{}}/>)
 expect(html).toContain('<summary>History</summary>')
 expect(html).not.toContain('open=""')
 expect(html).toContain('Restoring does not publish a Discord post.')
})

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import AccessPermissions, { changePermissionGroup } from './AccessPermissions'
const group = { label: 'CWL management', permissions: [{id:'roster',label:'Edit rosters',description:'Place accounts.'},{id:'publish',label:'Publish',description:'Show placements.'}] }
describe('permission switches', () => {
  it('changes only listed section permissions and avoids duplicate grants', () => {
    expect(changePermissionGroup(['clans','roster'],group,true)).toEqual(['clans','roster','publish'])
    expect(changePermissionGroup(['clans','roster','publish'],group,false)).toEqual(['clans'])
  })
  it('shows partial counts and explicit accessible switch labels without disabling individual controls', () => {
    const html=renderToStaticMarkup(<AccessPermissions groups={[group]} selected={['roster']} disabled={false} onChange={()=>{}} />)
    expect(html).toContain('1/2 enabled')
    expect(html).toContain('All CWL management actions')
    expect(html.match(/role="switch"/g)).toHaveLength(3)
    expect(html.match(/checked=""/g)).toHaveLength(1)
    expect(html).not.toContain('disabled=""')
  })
})

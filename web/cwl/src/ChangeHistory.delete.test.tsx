// @vitest-environment happy-dom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import ChangeHistory from './ChangeHistory'
const state = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('./api', () => ({ api: state.api }))
it('offers only the before snapshot for a deleted command', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  state.api.mockResolvedValue({ entries: [{ id: 'deleted', actor_name: 'Staff', at: new Date().toISOString(), action: 'delete', status: 'saved', changed: ['command'], before: { command: '!cwl' }, after: {} }] })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(<ChangeHistory target="/manage/text-commands/%21cwl" revision="current" disabled={false} onBusy={() => {}} onRestored={async () => {}} />))
    const details = host.querySelector('details')!
    await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')) })
    const labels = [...host.querySelectorAll('button')].map(button => button.textContent?.trim())
    expect(labels).toContain('Restore before this change')
    expect(labels).not.toContain('Restore this version')
  } finally { await act(async () => root.unmount()); host.remove(); state.api.mockReset() }
})

import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import SavedSignups from './SavedSignups'
import type { Signup } from './api'

function render(canMove: boolean, busy = false) {
  return renderToStaticMarkup(<SavedSignups
    signups={[{ tag: '#P2Y', player_name: 'Saved warrior', pool: 'lazy' } as Signup]}
    accounts={[]} editable busy={busy} canMove={canMove}
    headingRef={{ current: null }} onSave={async () => ({ saved: [], error: null })}
    onDirty={() => {}} onWithdraw={() => {}}
  />)
}

describe('saved signup account availability', () => {
  it('explains a missing link without hiding the saved signup', () => {
    const html = render(true)
    expect(html).toContain('Saved warrior')
    expect(html).toContain('Check its Discord link')
    expect(html).toMatch(/disabled="">Change CWL pool/)
  })
  it('does not claim an account is unlinked when the provider is unavailable', () => {
    expect(render(false)).not.toContain('Check its Discord link')
  })
  it('keeps the saved record visible while links are still being checked', () => {
    const html = render(false, true)
    expect(html).toContain('Saved warrior')
    expect(html).not.toContain('Check its Discord link')
    expect(html).toMatch(/disabled="">Withdraw signup/)
  })
})

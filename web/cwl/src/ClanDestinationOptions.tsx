import type { Pool } from './api'
import { assignmentOptions, type RosterClan } from './roster'

export default function ClanDestinationOptions({ clans, current, pool }: {
  clans: RosterClan[]
  current?: string | null
  pool?: Pool
}) {
  const eligible = assignmentOptions(clans, pool)
  const currentClan = clans.find(clan => clan.tag === current)
  const outsideLazy = pool === 'lazy' && currentClan && !currentClan.archived && currentClan.pool !== 'lazy'
  return <>
    {outsideLazy && <option value={current!} disabled>Current placement (not a Lazy host)</option>}
    {(['main', 'lazy', null] as const).map(groupPool => {
      const group = eligible.filter(clan => clan.pool === groupPool)
      if (!group.length) return null
      return <optgroup key={groupPool || 'unset'} label={groupPool === 'main' ? 'Main CWL' : groupPool === 'lazy' ? 'Lazy CWL' : 'Group not set'}>
        {group.map(clan => <option key={clan.tag} value={clan.tag}
          disabled={clan.assigned_count >= clan.effective_capacity && clan.tag !== current}>
          {clan.name} · {clan.assigned_count}/{clan.effective_capacity}{clan.assigned_count >= clan.effective_capacity ? ' · Full' : ''}
        </option>)}
      </optgroup>
    })}
  </>
}

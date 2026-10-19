export type Timing = { mode?: string; at?: string; day?: number; hour?: number; minute?: number; month_offset?: number; month_end_offset_days?: number; offset_minutes?: number; after?: string; [key: string]: unknown }
export type Variant = { title: string; body: string; media_url: string; destination_channel_id: string; role_ids: string[]; enabled: boolean; buttons: { label: string; url: string; emoji?: string }[] }
export type CampaignMessage = { enabled: boolean; label: string; schedule: Timing; variants: Record<'main' | 'lazy', Variant> }
export type Campaign = { timezone: string; paused: boolean; signup_deadline: Timing | string; reminder_sequence: { enabled: boolean; mode?: string; count?: number; interval_hours?: number; final_hours?: number; min_gap_hours?: number }; messages: Record<string, CampaignMessage> }
export type Occurrence = { id: string; message_id: string; variant: string; run_at: string | null; status?: string }
export type CampaignState = { cycle: string | null; generation: string | null; worker_ready: boolean; schedule_synced?: boolean; schedule_sync_at?: string | null; activated: boolean; campaign: Campaign | null; schedule: Occurrence[]; deadline?: string; history?: Record<string, unknown>[]; signup_open: boolean; protected_sent?: string[]; warning?: string; schedule_sync_pending?: boolean; sent_occurrences?: string[]; skipped?: string[]; deliveries?: Record<string, unknown>[] }
// Only editable fields travel to the API. Button destinations are deliberately absent.
export function campaignPatch(original: Campaign, edited: Campaign) {
  const patch: Record<string, unknown> = {}
  for (const key of ['timezone', 'signup_deadline', 'reminder_sequence'] as const) {
    if (JSON.stringify(original[key]) !== JSON.stringify(edited[key])) patch[key] = edited[key]
  }
  const messages: Record<string, unknown> = {}
  for (const [id, value] of Object.entries(edited.messages)) {
    const before = original.messages[id]
    if (!before || id === 'roster') continue
    const changes: Record<string, unknown> = {}
    for (const key of ['enabled', 'schedule'] as const) if (JSON.stringify(before[key]) !== JSON.stringify(value[key])) changes[key] = value[key]
    const variants: Record<string, unknown> = {}
    for (const pool of ['main', 'lazy'] as const) {
      const change: Record<string, unknown> = {}
      for (const key of ['title', 'body', 'media_url', 'destination_channel_id', 'role_ids', 'enabled'] as const) {
        if (JSON.stringify(before.variants[pool][key]) !== JSON.stringify(value.variants[pool][key])) change[key] = value.variants[pool][key]
      }
      if (Object.keys(change).length) variants[pool] = change
    }
    if (Object.keys(variants).length) changes.variants = variants
    if (Object.keys(changes).length) messages[id] = changes
  }
  if (Object.keys(messages).length) patch.messages = messages
  return patch
}
export function displayTime(value?: string | null) {
  if (!value) return 'Manual · no scheduled send'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

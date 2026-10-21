export type ReminderSettings = {
  enabled: boolean
  channel_id: string
  war_started: boolean
  minutes: number[]
  audience: 'remaining' | 'zero'
}

export type DeliveryReceipt = {
  at: string
  event: string
  status: string
  test: boolean
  url?: string
  urls?: string[]
  detail?: string
}

export type ReminderData = {
  settings: ReminderSettings
  revision: string
  history: DeliveryReceipt[]
  status?: { checked_at: string; detail: string } | null
}

export type ReminderMessage = { content: string }

export const timeLabel = (minutes: number) => {
  if (minutes % 60 === 0) return `${minutes / 60}h`
  const hours = Math.floor(minutes / 60)
  return `${hours ? `${hours}h ` : ''}${minutes % 60}m`
}

export function addReminderTime(times: number[], amount: string, unit: number): number[] {
  const minutes = Number(amount) * unit
  if (!amount.trim() || !Number.isInteger(minutes) || minutes < 1 || minutes > 1440) {
    throw new Error('Enter a time between 1 minute and 24 hours.')
  }
  return [...new Set([...times, minutes])].sort((a, b) => b - a)
}

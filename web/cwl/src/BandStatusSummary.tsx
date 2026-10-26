import type { ManagementField } from './serverManagement'

const primaryKeys = new Set([
  'task',
  'key',
  'health',
  'last_success',
  'checked_at',
])

const freshWarning =
  'Use Check status for current bot information. Debug resets when the bot restarts.'

export function bandStatusWarning(warning: string) {
  return warning === freshWarning
    ? 'Check status for current information.'
    : warning
}

function timestamp(value: ManagementField['value']) {
  if (typeof value !== 'string') return null
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.exec(value)
  if (!match) return null
  const [, year, month, day] = match
  if (Number(day) > new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate()) {
    return null
  }
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

function display(value: ManagementField['value']) {
  if (typeof value === 'boolean') return value ? 'On' : 'Off'
  return String(value ?? 'Not available')
}

function statusValue(field: ManagementField) {
  const date = ['checked_at', 'last_success'].includes(field.key)
    ? timestamp(field.value)
    : null
  if (!date) return display(field.value)
  return (
    <time dateTime={String(field.value)}>
      {date.toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        timeZoneName: 'short',
      })}
    </time>
  )
}

function StatusList({
  fields,
  label = 'Current status',
}: {
  fields: ManagementField[]
  label?: string
}) {
  return (
    <dl className="manage-status-summary" aria-label={label}>
      {fields.map((field) => (
        <div key={field.key}>
          <dt>{field.label}</dt>
          <dd>{statusValue(field)}</dd>
        </div>
      ))}
    </dl>
  )
}

export default function BandStatusSummary({
  fields,
}: {
  fields: ManagementField[]
}) {
  // Older or partial responses still need to show every field they supply.
  if (!fields.some((field) => field.key === 'task')) {
    return <StatusList fields={fields} />
  }

  const startup = fields.find(
    (field) => field.key === 'startup' && display(field.value) !== '✅ Healthy',
  )
  const problem = fields.find(
    (field) =>
      field.key === 'last_error' && display(field.value) !== 'None recorded',
  )
  const primary = fields.filter(
    (field) =>
      primaryKeys.has(field.key) || field === startup || field === problem,
  )
  const details = fields.filter((field) => !primary.includes(field))

  return (
    <div className="band-status">
      <StatusList fields={primary} />
      {fields.some(
        (field) =>
          field.key === 'task' && display(field.value) === 'Status unavailable',
      ) && (
        <p className="small">
          Last successful checks and recorded problems are historical. Check status
          for current bot information.
        </p>
      )}
      {details.length > 0 && (
        <details className="manage-more-options">
          <summary>Technical status details</summary>
          <StatusList fields={details} label="Technical status details" />
          {fields.some((field) => field.key === 'debug') && (
            <p className="small">Debug logging resets when the bot restarts.</p>
          )}
        </details>
      )}
    </div>
  )
}

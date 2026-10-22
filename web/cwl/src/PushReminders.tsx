import DashboardIcon from './DashboardIcon'
import { useEffect, useRef, useState } from 'react'
import { api, type Account } from './api'
import {
  PushPermissionError,
  getBrowserSubscription,
  enableBrowserPush,
  disableBrowserPush,
  subscriptionId,
} from './webPush'
import usePushPermission from './usePushPermission'
import PushPermissionHelp from './PushPermissionHelp'
import TownHallIcon from './TownHallIcon'
import './PushReminders.css'
export type ReminderSubscription = {
  id: string
  enabled: boolean
  tags: string[]
  war: boolean
  cwl: boolean
  offsets: number[]
  updated_at?: number
}
type PushStatus = {
  available: boolean
  public_key: string
  subscriptions: ReminderSubscription[]
}
type InstallEvent = Event & {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: string }>
}
export default function PushReminders({ accounts }: { accounts: Account[] }) {
  const { support, refreshPermission } = usePushPermission()
  const inFlight = useRef(false)
  const mounted = useRef(true)
  const edited = useRef(false)
  const loadSequence = useRef(0)
  const [permissionIssue, setPermissionIssue] = useState(false)
  const [status, setStatus] = useState<PushStatus | null>(null)
  const [current, setCurrent] = useState<ReminderSubscription | null>(null)
  const [tags, setTags] = useState<string[]>([])
  const [war, setWar] = useState(true)
  const [cwl, setCwl] = useState(true)
  const [offsets, setOffsets] = useState<number[]>([120])
  const validTimes =
    offsets.length > 0 &&
    offsets.every((value) => value >= 1 && value <= 1440) &&
    new Set(offsets).size === offsets.length
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [install, setInstall] = useState<InstallEvent | null>(null)
  const load = async (restoreChoices = false) => {
    const turn = ++loadSequence.current
    const result = await api<PushStatus>('/push')
    const browser = await getBrowserSubscription()
    const id = browser ? await subscriptionId(browser) : null
    if (!mounted.current || turn !== loadSequence.current) return
    const saved = result.subscriptions.find((item) => item.id === id) || null
    setStatus(result)
    setCurrent(saved)
    if (restoreChoices && !edited.current && saved) {
      setTags(saved.tags)
      setWar(saved.war)
      setCwl(saved.cwl)
      setOffsets(saved.offsets)
    }
  }
  useEffect(() => {
    mounted.current = true
    void load(true).catch((cause) => {
      if (mounted.current)
        setError(
          cause instanceof Error
            ? cause.message
            : 'Reminder settings unavailable',
        )
    })
    const capture = (event: Event) => {
      event.preventDefault()
      setInstall(event as InstallEvent)
    }
    window.addEventListener('beforeinstallprompt', capture)
    return () => {
      mounted.current = false
      ++loadSequence.current
      window.removeEventListener('beforeinstallprompt', capture)
    }
  }, [])
  const act = async (work: () => Promise<void>) => {
    if (inFlight.current) return
    inFlight.current = true
    ++loadSequence.current // An earlier settings read must not overwrite this action.
    setBusy(true)
    setError('')
    setNotice('')
    setPermissionIssue(false)
    try {
      await work()
    } catch (cause) {
      if (mounted.current) {
        setPermissionIssue(cause instanceof PushPermissionError)
        setError(
          cause instanceof Error ? cause.message : 'Request failed. Try again.',
        )
      }
    } finally {
      inFlight.current = false
      if (mounted.current) {
        setBusy(false)
        refreshPermission()
      }
    }
  }
  const enable = () => {
    if (
      inFlight.current ||
      !status?.available ||
      !tags.length ||
      !validTimes ||
      (!war && !cwl)
    )
      return
    // act invokes work synchronously: permission is requested on this click,
    // before any fetch or worker registration can consume user activation.
    void act(async () => {
      const subscription = await enableBrowserPush(status.public_key)
      const saved = await api<ReminderSubscription>(
        '/push/subscriptions',
        'PUT',
        {
          subscription: subscription.toJSON(),
          enabled: true,
          tags,
          war,
          cwl,
          offsets,
        },
      )
      if (!mounted.current) return
      setCurrent(saved)
      setStatus((value) =>
        value
          ? {
              ...value,
              subscriptions: [
                ...value.subscriptions.filter((item) => item.id !== saved.id),
                saved,
              ],
            }
          : value,
      )
      setNotice('Reminder settings saved for this device.')
    })
  }
  useEffect(() => {
    if (support.permission === 'granted' && permissionIssue) {
      setPermissionIssue(false)
      setError('')
      setNotice(
        'Browser permission is allowed. Select Enable notifications to finish setup with your chosen accounts and times.',
      )
    }
  }, [support.permission, permissionIssue])
  const recheckPermission = () => {
    refreshPermission()
    setError('')
    setPermissionIssue(false)
    setNotice(
      'Permission checked. If allowed, select Enable notifications to finish setup or save your choices.',
    )
  }
  const visible = accounts.filter((account) =>
    `${account.name} ${account.tag} ${account.current_clan_name || ''}`
      .toLowerCase()
      .includes(search.trim().toLowerCase()),
  )
  const dirty =
    !!current &&
    (JSON.stringify([...tags].sort()) !==
      JSON.stringify([...current.tags].sort()) ||
      war !== current.war ||
      cwl !== current.cwl ||
      JSON.stringify([...offsets].sort()) !==
        JSON.stringify([...current.offsets].sort()))
  return (
    <details className="card push-reminders">
      <summary>
        <span>
          <DashboardIcon name="bell" /> Notifications
        </span>
        <span className="badge">
          {current?.enabled && support.permission === 'granted'
            ? 'On for this device'
            : support.permission === 'denied'
              ? 'Permission blocked'
              : 'Off for this device'}
        </span>
      </summary>
      <p>Reminders for your accounts with War or CWL attacks left.</p>
      {!status && !error && <p role="status">Loading reminder settings…</p>}
      {!support.supported && <p className="notice">{support.reason}</p>}
      {support.permission === 'denied' && (
        <p className="notice">
          Notifications are blocked on this device. Open Notification help below
          for the steps to allow them.
        </p>
      )}
      {status && !status.available && (
        <p className="notice">
          Notifications are not ready yet. Your choices have not been enabled.
        </p>
      )}
      {error && (
        <div className="notice error" role="alert">
          <p>{error}</p>
          {permissionIssue ? (
            <>
              {support.permission !== 'denied' && (
                <button disabled={busy} onClick={enable}>
                  Try permission again
                </button>
              )}
            </>
          ) : (
            <button disabled={busy} onClick={() => void act(() => load())}>
              Reload settings
            </button>
          )}
        </div>
      )}
      {notice && (
        <p className="notice success" role="status">
          {notice}
        </p>
      )}
      <fieldset
        disabled={busy}
        onChange={() => {
          edited.current = true
        }}
        onClick={() => {
          edited.current = true
        }}
      >
        <legend>Remind me about</legend>
        <div className="push-options">
          <label>
            <input
              type="checkbox"
              checked={war}
              onChange={(event) => setWar(event.target.checked)}
            />
            War
          </label>
          <label>
            <input
              type="checkbox"
              checked={cwl}
              onChange={(event) => setCwl(event.target.checked)}
            />
            CWL
          </label>
        </div>
      </fieldset>
      <fieldset
        disabled={busy}
        onChange={() => {
          edited.current = true
        }}
        onClick={() => {
          edited.current = true
        }}
      >
        <legend>Remind me before war ends</legend>
        <p className="small">
          One reminder per clan at each time. Up to five times.
        </p>
        <div className="push-times">
          {offsets.map((value, index) => (
            <div className="push-time-row" key={index}>
              <span className="push-time-number">{index + 1}.</span>
              <label>
                Hours
                <select
                  aria-label={`Reminder ${index + 1} hours`}
                  value={Math.floor(value / 60)}
                  onChange={(event) => {
                    const hours = Number(event.target.value)
                    setOffsets((current) =>
                      current.map((item, i) =>
                        i === index
                          ? hours * 60 + (hours === 24 ? 0 : item % 60)
                          : item,
                      ),
                    )
                  }}
                >
                  {Array.from({ length: 25 }, (_, hour) => (
                    <option key={hour} value={hour}>
                      {hour}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Minutes
                <select
                  aria-label={`Reminder ${index + 1} minutes`}
                  value={value % 60}
                  disabled={value === 1440}
                  onChange={(event) =>
                    setOffsets((current) =>
                      current.map((item, i) =>
                        i === index
                          ? Math.floor(item / 60) * 60 +
                            Number(event.target.value)
                          : item,
                      ),
                    )
                  }
                >
                  {Array.from({ length: 60 }, (_, minute) => (
                    <option key={minute} value={minute}>
                      {minute.toString().padStart(2, '0')}
                    </option>
                  ))}
                </select>
              </label>
              <button
                type="button"
                aria-label={`Remove reminder ${index + 1}`}
                onClick={() =>
                  setOffsets((current) => current.filter((_, i) => i !== index))
                }
              >
                Remove
              </button>
            </div>
          ))}
        </div>
        {offsets.length < 5 && (
          <button
            type="button"
            onClick={() =>
              setOffsets((current) => [
                ...current,
                [120, 30, 360, 60, 15, 5].find(
                  (value) => !current.includes(value),
                )!,
              ])
            }
          >
            ＋ Add reminder time
          </button>
        )}
        {!validTimes && (
          <p className="notice" role="status">
            Choose at least one time from 1 minute to 24 hours. Each time must
            be different.
          </p>
        )}
      </fieldset>
      <details className="push-account-picker">
        <summary>
          Accounts · {tags.length} selected <span>Choose accounts</span>
        </summary>
        <fieldset
          disabled={busy}
          onChange={() => {
            edited.current = true
          }}
          onClick={() => {
            edited.current = true
          }}
        >
          <legend>Accounts to include</legend>
          <label>
            Find an account
            <input
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Name, tag or current clan"
            />
          </label>
          <div className="push-options">
            <button
              type="button"
              onClick={() => setTags(accounts.map((account) => account.tag))}
            >
              Select all linked accounts
            </button>
            <button type="button" onClick={() => setTags([])}>
              Clear
            </button>
          </div>
          <div className="push-accounts">
            {visible.map((account) => (
              <label key={account.tag}>
                <input
                  type="checkbox"
                  checked={tags.includes(account.tag)}
                  onChange={(event) =>
                    setTags((current) =>
                      event.target.checked
                        ? [...current, account.tag]
                        : current.filter((tag) => tag !== account.tag),
                    )
                  }
                />
                <TownHallIcon level={account.town_hall} />
                <span>
                  <strong>{account.name}</strong>
                  <small>
                    {account.tag} ·{' '}
                    {account.current_clan_name || 'No current clan'}
                  </small>
                </span>
              </label>
            ))}
          </div>
          {!accounts.length && (
            <p>Link your Clash accounts to select them here.</p>
          )}
        </fieldset>
      </details>
      {!war && !cwl && (
        <p className="small" role="status">
          Choose War, CWL, or both.
        </p>
      )}
      {!tags.length && (
        <p className="small">
          Choose at least one account to enable reminders.
        </p>
      )}
      <div className="push-actions">
        <button
          className="primary"
          disabled={
            busy ||
            !status?.available ||
            !support.supported ||
            support.permission === 'denied' ||
            !tags.length ||
            !validTimes ||
            (!war && !cwl)
          }
          onClick={enable}
        >
          {busy
            ? 'Working…'
            : current?.enabled && support.permission === 'granted'
              ? 'Save changes'
              : 'Enable notifications'}
        </button>
        {current?.enabled && (
          <button
            disabled={busy}
            onClick={() =>
              void act(async () => {
                await api(`/push/subscriptions/${current.id}`, 'DELETE')
                await disableBrowserPush()
                setCurrent(null)
                await load()
                setNotice('Notifications are off for this device.')
              })
            }
          >
            Turn off
          </button>
        )}
      </div>
      {dirty && <small role="status">Unsaved changes</small>}
      <details className="push-tools">
        <summary>Notification help &amp; test</summary>
        <p className="small">
          Permission on this device:{' '}
          <strong>
            {support.permission === 'granted'
              ? 'Allowed'
              : support.permission === 'denied'
                ? 'Blocked'
                : support.permission === 'default'
                  ? 'Not allowed yet'
                  : 'Unavailable'}
          </strong>
        </p>
        <div className="push-actions">
          <button type="button" disabled={busy} onClick={recheckPermission}>
            Recheck permission
          </button>
          {current?.enabled && (
            <>
              <button
                disabled={busy || dirty || support.permission !== 'granted'}
                onClick={() =>
                  void act(async () => {
                    await api(
                      `/push/subscriptions/${current.id}/test`,
                      'POST',
                      {},
                    )
                    setNotice(
                      'Test notification accepted by the push service. Check this device’s notifications.',
                    )
                  })
                }
              >
                Send test notification
              </button>
            </>
          )}
        </div>
        {dirty && <small>Save your changes before testing.</small>}
        <PushPermissionHelp
          expanded={
            permissionIssue ||
            support.permission === 'denied' ||
            !support.supported
          }
        />
        {install && (
          <button
            onClick={() =>
              void install
                .prompt()
                .then(() => install.userChoice)
                .then(() => setInstall(null))
            }
          >
            Install Warriors United app ↗
          </button>
        )}
        <p className="small">
          Reminders can arrive while the app is closed. Device settings,
          connection issues or delayed game data can affect delivery.
          Unavailable war data is skipped.
        </p>
        <p className="small">
          Reminders use the account’s war clan, even if it has moved. Select and
          save newly linked accounts to include them.
        </p>
        {!!status?.subscriptions.some((item) => item.id !== current?.id) && (
          <details>
            <summary>Other saved devices</summary>
            <p className="small">Remove a device to stop reminders there.</p>
            {status.subscriptions
              .filter((item) => item.id !== current?.id)
              .map((item, index) => (
                <div className="push-device" key={item.id}>
                  <span>
                    Device {index + 1} · {item.enabled ? 'On' : 'Off'}
                    <small>
                      {item.updated_at
                        ? `Updated ${new Date(item.updated_at * 1000).toLocaleString()}`
                        : ''}
                    </small>
                  </span>
                  <button
                    disabled={busy}
                    onClick={() =>
                      void act(async () => {
                        await api(`/push/subscriptions/${item.id}`, 'DELETE')
                        await load()
                        setNotice('Reminders removed for that device.')
                      })
                    }
                  >
                    Remove device
                  </button>
                </div>
              ))}
          </details>
        )}
        <p className="small">
          Notification text can appear on your lock screen. Signing out here
          turns off reminders on this browser; other devices keep their own
          settings.
        </p>
      </details>
    </details>
  )
}

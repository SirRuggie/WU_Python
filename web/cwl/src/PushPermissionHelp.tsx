import { pushPlatform } from './webPush'

export default function PushPermissionHelp({
  expanded = false,
}: {
  expanded?: boolean
}) {
  const platform = pushPlatform()
  return (
    <details className="push-help" open={expanded || undefined}>
      <summary>Setup instructions</summary>
      {platform === 'android' ? (
        <ol>
          <li>
            If you opened this page from another app and no prompt appears, open
            that app’s ⋮ menu. Open the page in Chrome or your full browser.
            Use a normal tab. Do not use Incognito.
          </li>
          <li>
            In Chrome, select the site controls beside the address. Then select
            Permissions → Notifications → Allow. You can also use ⋮ → Settings →
            Site settings → Notifications. The permission prompt can appear near
            the address bar.
          </li>
          <li>
            In Android Settings → Apps → your browser → Notifications, allow
            notifications. If you installed Warriors United, check its
            notification settings too.
          </li>
          <li>
            If Chrome says “Managed by Warriors United”, the installed app
            controls permission. Allow notifications. Close the app from recent
            apps. Open it again from its home-screen icon. Then select Recheck
            permission here.
          </li>
        </ol>
      ) : platform === 'ios' ? (
        <ol>
          <li>
            Use iOS or iPadOS 16.4 or later. Add Warriors United to your Home
            Screen with the Share menu in your browser. Then open the Home
            Screen app.
          </li>
          <li>
            Select your accounts and times here. Select Enable notifications.
            Then allow the prompt.
          </li>
          <li>
            If blocked, open Settings → Notifications → Warriors United and
            allow notifications, then return here.
          </li>
        </ol>
      ) : (
        <ol>
          <li>Open the dashboard in a normal browser tab over HTTPS.</li>
          <li>
            Use the site controls beside the address to allow notifications.
            Check your computer’s notification settings for this browser too.
          </li>
          <li>
            Return here, recheck permission, then enable notifications.
            Installing the dashboard is optional.
          </li>
        </ol>
      )}
      <p className="small">
        This dashboard cannot change your browser or phone permissions. After
        you turn on notifications, select Send test notification to check
        delivery. Do Not Disturb and device settings can stop alerts, also when
        the browser allows them.
      </p>
    </details>
  )
}

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
            If you opened this page from another app and no prompt appears, use
            its ⋮ menu to open in Chrome or your full browser. Use a normal tab,
            not Incognito.
          </li>
          <li>
            In Chrome, tap the site controls beside the address → Permissions →
            Notifications → Allow. You can also check ⋮ → Settings → Site
            settings → Notifications. A quiet permission prompt may appear near
            the address bar.
          </li>
          <li>
            In Android Settings → Apps → your browser → Notifications, allow
            notifications. If you installed Warriors United, check its
            notification settings too.
          </li>
          <li>
            If Chrome says “Managed by Warriors United”, the installed app
            controls permission. After allowing it, close the app from recent
            apps and reopen it from its home-screen icon, then recheck
            permission here.
          </li>
        </ol>
      ) : platform === 'ios' ? (
        <ol>
          <li>
            Use iOS or iPadOS 16.4 or later. Add Warriors United to your Home
            Screen from the browser’s Share menu, then open that Home Screen
            app.
          </li>
          <li>
            Choose your accounts and times here, tap Enable notifications, and
            allow the prompt.
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
        This website cannot change browser or phone permissions for you. Once
        enabled, use Send test notification to check delivery. Focus/Do Not
        Disturb and device settings can silence alerts even when browser
        permission is allowed.
      </p>
    </details>
  )
}

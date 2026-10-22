# Browser notifications: permission recovery

The dashboard uses standard HTTPS Web Push, a root-scoped service worker, VAPID,
and durable server-side subscription/delivery records. Android and desktop users
do not need to install the site. iOS/iPadOS requires a supported Home Screen web
app (16.4 or later). Browser and operating-system permission remain user-controlled.

## October 22 investigation and change

The reported message corresponds to an undecided (`default`) permission result;
it does not identify whether the prompt expired, was dismissed, or was suppressed
by browser context/settings. Chrome documents non-blocking Android prompts that
can time out and permission grants later from Site Controls. The old Retry settings
button only reloaded server settings, and permission changes were not observed.
The initial permission request already ran from the user's click; that is retained.

- Separate undecided and blocked results. Retry permission is a real user-triggered
  permission request. Do not re-prompt when already blocked.
- Observe Permissions API changes, with focus/pageshow/visibility fallbacks.
  Later grants update the UI; the user explicitly selects Enable to complete
  subscription with their current account/time choices. No automatic enrollment.
- Show browser permission separately from saved device state. Revocation changes
  the badge to Blocked and disables sending a test until permission is allowed.
- Explain full-browser fallback, Chrome site controls, Android notification
  settings and private-browsing limitations. Do not claim all Custom Tabs lack push.
- Preserve selected accounts/times when rechecking or reloading settings. Ignore
  obsolete reads and guard concurrent actions. Never automatically replay a test.
- Bound waiting for worker activation and provide a visible retryable error.

## Research

- [Chrome: lighter Android notification prompts](https://developer.chrome.com/blog/notification-prompts-android)
  documents prompt timeout to default and permission change observation.
- [Chrome Android notification settings](https://support.google.com/chrome/answer/3220216?co=GENIE.Platform%3DAndroid&hl=en)
  documents site controls, quiet prompts, private browsing and revoked permissions.
- [MDN: notification permission](https://developer.mozilla.org/en-US/docs/Web/API/Notification/requestPermission_static)
  explains granted/default/denied and secure user-triggered requests.
- [Apple: Web Push](https://developer.apple.com/documentation/usernotifications/sending-web-push-notifications-in-web-apps-and-browsers)
  documents Safari/Home Screen support and user interaction requirements.
- [Chrome: Custom Tabs](https://developer.chrome.com/docs/android/custom-tabs)
  distinguishes browser-powered tabs from embedded WebViews.

## Validation and limits

An isolated browser fixture replaced permission/subscription APIs; it never prompted
a real permission grant or sent a notification. It verified: default failure,
retry increments prompt count, later granted permission updates without reload,
selected accounts survive, one subscription save, revoked permission changes status
and disables enable/test. Layout checks used 320px, 390px and desktop widths.
Unit regressions cover direct-click ordering, default/denied/granted, no repeated
blocked prompt, late permission events/cleanup, unsupported query fallback,
service worker activation timeout, Android browser support and unavailable Push API.
Backend tests cover auth/CSRF/ownership, linked accounts, durable dedup/restarts and
expired subscriptions. Production service, VAPID configuration presence, worker
logs and static assets were checked without exposing keys or sending messages.

No physical Android, Chrome Custom Tab, Safari/iOS, OS notification tray, or live
push delivery was tested. Backend push acceptance does not prove device delivery.
The existing scheduler's narrow due window may skip alerts during an extended
upstream outage; it intentionally avoids late catch-up alerts. That is separate
from the permission issue in the screenshot.

Validation totals for this change: 275 frontend tests and 15 focused push backend
tests passed. Required war-reminder validation also passed (185 backend tests,
1 skipped; 32 focused frontend checks). Existing aiohttp warnings remain.

## October 22: simpler reminder settings

Everyday controls now show War/CWL, reminder times, a compact selected-account
count with an expandable picker, and Enable/Save plus Turn off. Permission details,
recheck/test controls, installation advice, other saved devices and delivery
explanations live under “Notification help & test”. Errors and unsaved changes
remain visible outside that disclosure. Android help covers Chrome's delegated
“Managed by Warriors United” permission and relaunching the installed app.
No subscription storage, API authorization, scheduling or delivery changes.

Validation: 275 frontend tests, 15 push backend tests, and the war-reminder
validation gate passed (a temporary copy redirected only its build output to
/tmp so checks could not replace served production assets). Isolated browser
checks at 320/390/1280px covered account selection, permission grant, save,
disclosure visibility, dirty-state test blocking and a failed test with retained
settings; inspected widths had no horizontal overflow. Permission and transport
were simulated; no real push was sent. Existing build/aiohttp warnings remain.

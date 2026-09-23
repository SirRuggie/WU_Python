# LazyCWL return reminders

The old `/fwa lazycwl-*` commands now open `/lazycwl`.
See [the dashboard guide](lazycwl-dashboard.md) for current operation and storage.

The dashboard uses a dedicated reminder service and Mongo-backed saved rosters.
Its scheduler is in memory; startup restores enabled reminders from stored state.
The legacy `lazy_cwl_snapshots` collection remains available for migration.

Return reminders continue to use the existing shared destination channel. The
Reminders tab shows that destination before an administrator sends a reminder.

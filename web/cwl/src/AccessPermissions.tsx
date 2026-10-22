export type Permission = { id: string; label: string; description: string }
export type PermissionGroup = { label: string; permissions: Permission[] }
export function changePermissionGroup(selected: string[], group: PermissionGroup, enabled: boolean) {
  const ids = new Set(group.permissions.map(permission => permission.id))
  return enabled ? [...new Set([...selected, ...ids])] : selected.filter(id => !ids.has(id))
}
export default function AccessPermissions({ groups, selected, disabled, onChange }: {
  groups: PermissionGroup[]; selected: string[]; disabled: boolean; onChange: (values: string[]) => void
}) {
  return <div className="access-permissions">{groups.map(group => {
    const count = group.permissions.filter(permission => selected.includes(permission.id)).length
    return <fieldset key={group.label} disabled={disabled}>
      <legend>{group.label} <small>{count}/{group.permissions.length} enabled</small></legend>
      <label className="access-switch-row access-group-switch">
        <span><strong>All actions in this section</strong><small>Enables the actions listed below. You can turn individual actions off.</small></span>
        <input type="checkbox" role="switch" aria-label={`All ${group.label} actions`} checked={count === group.permissions.length} onChange={event => onChange(changePermissionGroup(selected, group, event.target.checked))} />
      </label>
      {group.permissions.map(permission => <label className="access-switch-row" key={permission.id}>
        <span><strong>{permission.label}</strong><small>{permission.description}</small></span>
        <input type="checkbox" role="switch" checked={selected.includes(permission.id)} onChange={event => onChange(event.target.checked ? [...selected, permission.id] : selected.filter(id => id !== permission.id))} />
      </label>)}
    </fieldset>
  })}</div>
}

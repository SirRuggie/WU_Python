export function strikePermissions(permissions: string[] = [], isOwner = false) {
  const has = (permission: string) => isOwner || permissions.includes(permission)
  const manage = has('strikes')
  const add = has('strikes_add')
  const remove = has('strikes_remove')
  return { view: manage || add || remove, manage, add, remove }
}

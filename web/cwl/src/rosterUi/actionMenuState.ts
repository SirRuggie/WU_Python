let active: string | null = null;
const listeners = new Set<() => void>();
export function activeRosterActionMenu() {
  return active;
}
export function setRosterActionMenu(id: string | null) {
  if (active === id) return;
  active = id;
  listeners.forEach((listener) => listener());
}
export function subscribeRosterActionMenus(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
export function closeRosterActionMenus() {
  setRosterActionMenu(null);
}

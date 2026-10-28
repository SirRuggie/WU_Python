/** One Details surface owns navigation/discard prompts at a time. */
type Guard = (action: () => void) => void;
let activeGuard: Guard | null = null;
export function registerDetailsGuard(guard: Guard) {
  activeGuard = guard;
  return () => {
    if (activeGuard === guard) activeGuard = null;
  };
}
export function requestDetailsNavigation(action: () => void) {
  if (activeGuard) activeGuard(action);
  else action();
}
export function detailsAccount(search = location.search) {
  return new URLSearchParams(search).get("account");
}
export function detailsUrl(tag: string | null, href = location.href) {
  const url = new URL(href);
  if (tag) url.searchParams.set("account", tag);
  else url.searchParams.delete("account");
  return `${url.pathname}${url.search}${url.hash}`;
}

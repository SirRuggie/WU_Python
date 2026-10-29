/** Tour-only safety boundary; never persisted or shared between tabs. */
let active = false;
export function setTourReadOnly(value: boolean) {
  active = value;
}
export function isTourReadOnly() {
  return active;
}
export function assertTourRead(method: string) {
  if (active && method.toUpperCase() !== "GET")
    throw new Error("Practice — nothing saved.");
}
export type TourPage = "home" | "todo" | "register" | "saved" | "assignments";
export type SignupTourState =
  | "loading"
  | "open"
  | "closed"
  | "empty"
  | "all-signed";

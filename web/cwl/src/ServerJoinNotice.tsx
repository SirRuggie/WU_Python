import { ApiError } from "./api";

/** Permanent server invite approved by Ruggie on 2026-11-07. */
export const SERVER_INVITE_URL = "https://discord.gg/2edDGBStax";
export const JOIN_REQUIRED_TEXT =
  "Join the Warriors United Discord server to sign up.";

/** True when a signup save was refused because the person is not in the server. */
export function isJoinRequiredError(error: unknown) {
  return (
    error instanceof ApiError &&
    error.status === 403 &&
    error.message.startsWith(JOIN_REQUIRED_TEXT)
  );
}

export default function ServerJoinNotice() {
  return (
    <p className="inline-reason server-join-notice" role="status">
      {JOIN_REQUIRED_TEXT}{" "}
      <a href={SERVER_INVITE_URL} target="_blank" rel="noopener noreferrer">
        Join server
      </a>
    </p>
  );
}

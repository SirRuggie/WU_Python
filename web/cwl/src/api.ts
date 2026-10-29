import { fetchReadWithRetry } from "./readRetry";
import { clearSnapshots } from "./snapshotCache";
export type Pool = "main" | "lazy";
export type Session = {
  authenticated: true;
  access_warning?: string | null;
  user: {
    id: string;
    username: string;
    display_name?: string;
    avatar_url?: string | null;
  };
  dashboard_permissions?: string[];
  is_owner: boolean;
  can_edit: boolean;
  csrf_token: string;
};
export type Season = {
  id: number;
  label: string;
  status: string;
  signup_open: boolean;
  signup_deadline?: string | null;
  placements_by?: string | null;
};
export type FamilyClanStatus = "approved" | "outside" | "unknown";
export type Account = {
  current_clan_type?: string | null;
  war_weight?: number | null;
  tag: string;
  name: string;
  town_hall: number | null;
  current_clan_tag: string | null;
  current_clan_name: string | null;
  current_clan_badge_url?: string | null;
  verified: boolean;
  lazy_eligible: boolean;
  lazy_ineligible_reason: string | null;
  family_clan_status: FamilyClanStatus;
};
export type Signup = {
  assigned_clan_tag?: string | null;
  assigned_clan_name?: string | null;
  signup_clan_type?: string | null;
  fwa_main_warning?: boolean;
  has_staff_placement?: boolean;
  tag: string;
  user_id: string;
  pool: Pool;
  prefer_crystal_1_or_lower: boolean;
  player_name?: string;
  town_hall?: number | null;
  signup_clan_name?: string | null;
  signup_clan_tag?: string | null;
  family_clan_status?: FamilyClanStatus;
};
export type Clan = {
  cwl_league?: string | null;
  cwl_league_stale?: boolean;
  tag: string;
  name: string;
  archived: boolean;
  pool?: Pool | null;
};
export type Grant = {
  permissions?: string[];
  user_id: string;
  username?: string;
  granted_at?: string;
};
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
let csrfToken = "";
export function setCsrfToken(token: string) {
  csrfToken = token;
}
export function handleAuthorizationFailure(status: number, path = "") {
  if (status !== 401 && status !== 403) return;
  clearSnapshots();
  if (path !== "/auth/me")
    window.dispatchEvent(new Event("dashboard-access-changed"));
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetchReadWithRetry(`/api/cwl${path}`, {
      method,
      credentials: "same-origin",
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...(method === "GET" ? {} : { "X-CSRF-Token": csrfToken }),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    void reportBrowserIssue("network_error");
    throw new ApiError(
      "The CWL service is unavailable. Check your connection and try again.",
      0,
    );
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    handleAuthorizationFailure(response.status, path);
    const message =
      typeof data?.error === "string"
        ? data.error
        : typeof data?.message === "string"
          ? data.message
          : null;
    const fallback: Record<number, string> = {
      401: "Your Discord session has expired. Sign in again.",
      403: "You do not have access to this action.",
      404: "This item is no longer available.",
      409: "This account is already signed up for the other CWL pool for this season.",
      423: "Signups are closed for this season.",
      503: "Linked accounts or game data are temporarily unavailable. Try again shortly.",
    };
    throw new ApiError(
      (message ||
        fallback[response.status] ||
        `Request failed (${response.status}). Try again.`) +
        (data?.issue_reference ? ` Reference: ${data.issue_reference}` : ""),
      response.status,
    );
  }
  if (method !== "GET") clearSnapshots();
  return data as T;
}

export async function apiUpload<T>(path: string, file: File): Promise<T> {
  const response = await fetchReadWithRetry(`/api/cwl${path}`, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "X-CSRF-Token": csrfToken,
      "Content-Type": file.type || "application/octet-stream",
    },
    body: file,
  });
  const data = await response.json().catch(() => null);
  if (!response.ok)
    throw new ApiError(
      (data?.error ||
        "Image upload failed. Try a smaller PNG, JPEG, or WebP image.") +
        (data?.issue_reference ? ` Reference: ${data.issue_reference}` : ""),
      response.status,
    );
  return data as T;
}

let lastBrowserReport = 0;
export async function reportBrowserIssue(
  kind: "browser_error" | "unhandled_promise" | "network_error",
) {
  if (!csrfToken || Date.now() - lastBrowserReport < 60000) return;
  lastBrowserReport = Date.now();
  try {
    const response = await fetch("/api/cwl/issues/browser", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({ kind }),
    });
    if (response.ok) {
      const data = await response.json();
      window.dispatchEvent(
        new CustomEvent("dashboard-issue", { detail: data.reference }),
      );
    }
  } catch {
    /* Offline reports cannot be delivered; never retry a user action. */
  }
}

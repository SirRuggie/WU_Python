// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const transport = vi.hoisted(() => vi.fn());
vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()),
  api: transport,
}));
import { ApiError } from "../api";
import MemberTimezones from "./MemberTimezones";
import Standardize from "./Standardize";
import type { Directory } from "./types";
const uid = "123456789012345678";
const directory: Directory = {
  permission: "member_roles",
  countries: [{ code: "US", flag: "🇺🇸", label: "United States" }],
  zones: [{ id: "gmt-5", label: "GMT-5 · US Eastern" }],
  members: [
    {
      discord_id: uid,
      name: "Ada",
      nickname: "Ada | EST 🇺🇸",
      bot: false,
      status: "Saved",
      profile: {
        zone_id: "gmt-5",
        gmt_label: "GMT-5",
        utc_offset_minutes: -300,
        country: "US",
        flag: "🇺🇸",
        name_source_tag: null,
        source: "staff",
        revision: 3,
      },
      parsed: { label: "EST", offsetMinutes: -300 },
      skip_reason: null,
    },
  ],
};
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  transport.mockReset();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("confirm", vi.fn(() => true));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function renderPage() {
  await act(async () => root.render(<MemberTimezones onDirty={() => {}} />));
}
async function click(text: string) {
  const button = [...host.querySelectorAll("button")].find(
    (x) => x.textContent === text,
  );
  expect(button).toBeTruthy();
  await act(async () => button!.click());
}
it("lists states, searches and edits without fetching a closed Standardize preview", async () => {
  transport.mockImplementation(async (path: string) =>
    path.endsWith("/choices")
      ? { accounts: [], suggested: null, complete: true }
      : directory,
  );
  await renderPage();
  expect(host.textContent).toContain("Saved");
  expect(host.textContent).toContain("GMT-5");
  expect(
    transport.mock.calls.every((c) => !String(c[0]).includes("preview")),
  ).toBe(true);
  await click("Edit Ada");
  expect(host.querySelector("input")?.value).toBe("Ada");
  expect(host.textContent).toContain("Also change the Discord nickname");
  expect(transport.mock.calls.some((c) => c[1] === "POST")).toBe(false);
});
it("clears protected member data when refresh loses permission", async () => {
  transport
    .mockResolvedValueOnce(directory)
    .mockRejectedValueOnce(new ApiError("Denied", 403));
  await renderPage();
  expect(host.textContent).toContain("Ada");
  await click("Refresh members");
  expect(host.textContent).not.toContain("Ada");
  expect(host.textContent).toContain("Your access changed");
});
it("preserves the editor after a conflict and never silently queues a nickname change", async () => {
  transport.mockImplementation(async (path: string, method?: string) => {
    if (method === "POST") throw new ApiError("Profile changed", 409);
    if (path.endsWith("/choices"))
      return { accounts: [], suggested: null, complete: true };
    return directory;
  });
  await renderPage();
  await click("Edit Ada");
  await click("Save profile");
  expect(host.textContent).toContain("Profile changed");
  expect(host.querySelector("input")?.value).toBe("Ada");
  const posted = transport.mock.calls.find((c) => c[1] === "POST")!;
  expect(posted[2].rename).toBe(false);
  expect(posted[2].revision).toBe(3);
});
it("unticked preview members are excluded from confirmation and uncertain results have no retry button", async () => {
  const rows = [
    {
      discord_id: uid,
      name: "Ada",
      old_nickname: "Old",
      new_nickname: "Ada | GMT-5 🇺🇸",
      revision: 3,
    },
    {
      discord_id: "234567890123456789",
      name: "Bob",
      old_nickname: "Bob",
      new_nickname: "Bob | GMT-5 🇺🇸",
      revision: 1,
    },
  ];
  transport.mockImplementation(async (path: string) => {
    if (path.endsWith("/runs")) return { runs: [] };
    if (path.endsWith("/preview")) return { token: "token", rows };
    if (path.endsWith("/confirm")) return { run_id: "run", state: "queued" };
    return {
      run_id: "run",
      state: "done",
      rows: [
        {
          ...rows[0],
          status: "uncertain",
          message: "Check Discord before repeating",
        },
      ],
    };
  });
  await act(async () =>
    root.render(<Standardize disabled={false} onDenied={() => {}} />),
  );
  const detail = host.querySelector("details")!;
  await act(async () => {
    detail.open = true;
    detail.dispatchEvent(new Event("toggle"));
  });
  await click("Preview all nickname changes");
  const checks = host.querySelectorAll<HTMLInputElement>(
    "input[type=checkbox]",
  );
  await act(async () => checks[1].click());
  await click("Confirm 1 nickname changes");
  const call = transport.mock.calls.find((c) =>
    String(c[0]).endsWith("/confirm"),
  )!;
  expect(call[2].selected).toEqual([uid]);
  expect(host.textContent).toContain("need manual checking");
  expect(
    [...host.querySelectorAll("button")].some((b) =>
      /retry/i.test(b.textContent || ""),
    ),
  ).toBe(false);
});

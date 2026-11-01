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
  vi.stubGlobal(
    "confirm",
    vi.fn(() => true),
  );
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
    (x) => x.textContent === text || x.getAttribute("aria-label") === text,
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
it("pages 560 compact members and keeps occasional actions above the directory", async () => {
  const many = {
    ...directory,
    members: Array.from({ length: 560 }, (_, i) => ({
      ...directory.members[0],
      discord_id: String(123456789012345000n + BigInt(i)),
      name: `Member ${String(i).padStart(3, "0")}`,
    })),
  };
  transport.mockResolvedValue(many);
  await renderPage();
  expect(host.querySelectorAll(".mt-member-row")).toHaveLength(25);
  expect(host.textContent).toContain("560 of 560");
  const actions = host.querySelector(".mt-top-actions")!,
    list = host.querySelector(".mt-member-list")!;
  expect(
    actions.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  await click("Next members");
  expect(
    host.querySelector(".mt-pagination span")?.getAttribute("aria-label"),
  ).toBe("Page 2 of 23");
  expect(host.querySelector(".mt-member-row")!.textContent).toContain(
    "Member 025",
  );
});
it("reloads a conflicting revision while keeping the draft for explicit reapply", async () => {
  let latest = false;
  const posts: unknown[] = [];
  transport.mockImplementation(
    async (path: string, method?: string, body?: unknown) => {
      if (method === "POST") {
        posts.push(body);
        throw new ApiError("Profile changed", 409);
      }
      if (path.endsWith("/choices"))
        return { accounts: [], suggested: null, complete: true };
      return {
        ...directory,
        members: [
          {
            ...directory.members[0],
            profile: {
              ...directory.members[0].profile!,
              revision: latest ? 4 : 3,
            },
          },
        ],
      };
    },
  );
  await renderPage();
  await click("Edit Ada");
  await act(async () => {
    const field = host.querySelector<HTMLInputElement>(".mt-editor input")!;
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(field, "Draft kept");
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click("Save profile");
  latest = true;
  await click("Reload latest and keep draft");
  expect(host.querySelector<HTMLInputElement>(".mt-editor input")!.value).toBe(
    "Draft kept",
  );
  expect(host.textContent).toContain("Your draft was kept");
  await click("Save profile");
  const first = posts[0] as { request_id: string; revision: number },
    second = posts[1] as { request_id: string; revision: number };
  expect(first.revision).toBe(3);
  expect(second.revision).toBe(4);
  expect(first.request_id).not.toBe(second.request_id);
});
it("uses a fresh identity only on an explicit retry of a confirmed failed save or import", async () => {
  const posts: { path: string; body: { request_id: string } }[] = [];
  transport.mockImplementation(
    async (path: string, method?: string, body?: { request_id: string }) => {
      if (method === "POST") {
        posts.push({ path, body: body! });
        return {
          request_id: `request${posts.length}`,
          status: "failed",
          status_url: "/fixture-status",
          message: "Confirmed failure",
        };
      }
      if (path.endsWith("/choices"))
        return { accounts: [], suggested: null, complete: true };
      return directory;
    },
  );
  await renderPage();
  await click("Edit Ada");
  await click("Save profile");
  await click("Save profile");
  expect(posts[0].body.request_id).not.toBe(posts[1].body.request_id);
  await click("Cancel");
});
it("retains the request identity after an unconfirmed transport failure", async () => {
  const ids: string[] = [];
  transport.mockImplementation(
    async (path: string, method?: string, body?: { request_id: string }) => {
      if (method === "POST") {
        ids.push(body!.request_id);
        throw new ApiError("Unconfirmed connection", 0);
      }
      if (path.endsWith("/choices"))
        return { accounts: [], suggested: null, complete: true };
      return directory;
    },
  );
  await renderPage();
  await click("Edit Ada");
  await click("Save profile");
  await click("Save profile");
  expect(ids).toHaveLength(2);
  expect(ids[0]).toBe(ids[1]);
});
it("makes complete row metadata accessible and exposes hierarchy reasons in the editor", async () => {
  const guard = "The server owner cannot be changed by this tool.";
  transport.mockImplementation(async (path: string) =>
    path.endsWith("/choices")
      ? { accounts: [], suggested: null, complete: true }
      : {
          ...directory,
          members: [{ ...directory.members[0], skip_reason: guard }],
        },
  );
  await renderPage();
  const row = host.querySelector<HTMLButtonElement>(".mt-member-row")!;
  const descriptions = row
    .getAttribute("aria-describedby")!
    .split(" ")
    .map((id) => host.querySelector(`#${id}`)?.textContent)
    .join(" ");
  expect(descriptions).toContain("Ada | EST");
  expect(descriptions).toContain(guard);
  await click("Edit Ada");
  expect(host.querySelector(".mt-editor")!.textContent).toContain(guard);
});
it("hides the member directory during a run and returns to it through Back", async () => {
  transport.mockImplementation(async (path: string) => {
    if (path.endsWith("/runs"))
      return { runs: [{ run_id: "run", state: "queued" }] };
    if (path.endsWith("/runs/run"))
      return {
        run_id: "run",
        state: "queued",
        started_by: uid,
        stopped_by: uid,
        rows: [
          {
            discord_id: uid,
            name: "Ada",
            status: "waiting",
            message: "Waiting",
          },
        ],
      };
    if (path.endsWith("/choices"))
      return { accounts: [], suggested: null, complete: true };
    return directory;
  });
  await renderPage();
  await click("Past runs");
  const details = host.querySelector(".mt-nickname-review")!;
  await act(async () => {
    const select = details.querySelector("select")!;
    select.value = "run";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(details.textContent).toContain("Renaming");
  expect(host.querySelector(".mt-member-list")).toBeNull();
  expect(host.textContent).not.toContain("Search members");
  const actions = host.querySelector(".mt-top-actions")!;
  expect(actions.textContent).toContain("Started by");
  expect(actions.textContent).toContain("Stopped by");
  expect(actions.textContent).not.toContain(uid);
  expect(
    transport.mock.calls.some(([path]) =>
      String(path).includes("staff-signup-members"),
    ),
  ).toBe(false);
  expect(
    [...actions.querySelectorAll(".user-display-name")].map(
      (n) => n.textContent,
    ),
  ).toContain("Ada");
  await click("Back to members");
  expect(host.querySelector(".mt-member-list")).not.toBeNull();
  await click("Edit Ada");
  await click("Cancel");
});
it("narrows the dashboard zone menu by country and supports Show all without nickname aliases", async () => {
  const au = [
    { id: "gmt+10", label: "GMT+10 · East (AEST/AEDT)" },
    { id: "gmt+9:30", label: "GMT+9:30 · Central (ACST/ACDT)" },
    { id: "gmt+8", label: "GMT+8 · West (AWST)" },
  ];
  const full = [...directory.zones, ...au];
  const fixture = {
    ...directory,
    zones: full,
    countries: [
      { ...directory.countries[0], zones: directory.zones },
      { code: "AU", flag: "🇦🇺", label: "Australia", zones: au },
    ],
  };
  transport.mockImplementation(async (path: string) =>
    path.endsWith("/choices")
      ? { accounts: [], suggested: null, complete: true }
      : fixture,
  );
  await renderPage();
  await click("Edit Ada");
  const country = host.querySelector<HTMLSelectElement>(
    'select[aria-label="Country"]',
  )!;
  const zone = host.querySelector<HTMLSelectElement>(
    'select[aria-label="Time zone"]',
  )!;
  await act(async () => {
    country.value = "AU";
    country.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(zone.options).toHaveLength(4);
  expect(zone.textContent).toContain("West (AWST)");
  await act(async () => {
    zone.value = "gmt+9:30";
    zone.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await act(async () =>
    [...host.querySelectorAll("label")]
      .find((label) =>
        label.textContent?.includes("Also change the Discord nickname"),
      )!
      .querySelector<HTMLInputElement>("input")!
      .click(),
  );
  expect(host.textContent).toContain("Ada | GMT+9:30 🇦🇺");
  await click("Show all zones");
  expect(zone.options).toHaveLength(5);
});

it("shows uncertain saves in the editor and gives an explicit retry a fresh receipt identity", async () => {
  transport.mockImplementation(
    async (path: string, _method?: string, body?: { request_id: string }) => {
      if (path.endsWith("/choices")) return { accounts: [], complete: true };
      if (path.endsWith("/save"))
        return {
          request_id: body!.request_id,
          status: "uncertain",
          status_url: "/receipt",
          message: "Check Discord before repeating this save.",
        };
      return directory;
    },
  );
  await renderPage();
  await click("Edit Ada");
  await click("Save profile");
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Check Discord",
  );
  await click("Save profile");
  const saves = transport.mock.calls.filter((c) =>
    String(c[0]).endsWith("/save"),
  );
  expect(saves).toHaveLength(2);
  expect(saves[0][2].request_id).not.toBe(saves[1][2].request_id);
});

it("replaces the member list and search with review and restores them on Back", async () => {
  transport.mockImplementation(async (path: string) => {
    if (path.endsWith("/import"))
      return { request_id: "import", status: "done", status_url: "/receipt" };
    if (path.endsWith("/preview"))
      return {
        token: "preview",
        rows: [
          {
            discord_id: uid,
            name: "Ada",
            old_nickname: "Old",
            new_nickname: "Ada | GMT-5 🇺🇸",
            revision: 3,
            category: "will_change",
          },
        ],
      };
    return directory;
  });
  await renderPage();
  await click("Review nicknames");
  expect(host.querySelector(".mt-member-list")).toBeNull();
  expect(host.textContent).not.toContain("Search members");
  expect(host.textContent).toContain("Search nicknames");
  await click("Back to members");
  expect(host.querySelector(".mt-member-list")).not.toBeNull();
  expect(host.textContent).toContain("Search members");
});

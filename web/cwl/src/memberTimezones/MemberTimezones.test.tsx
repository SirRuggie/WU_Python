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
    ".mt-list input[type=checkbox]",
  );
  await act(async () => checks[1].click());
  await click("Rename 1 members");
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

it("leaves a preserved unknown suffix unticked for explicit review", async () => {
  const rows = [
    {
      discord_id: uid,
      name: "Bob",
      old_nickname: "Bob | Co-Leader",
      new_nickname: "Bob | Co-Leader | GMT-5 🇺🇸",
      revision: 1,
      needs_review: true,
    },
  ];
  transport.mockImplementation(async (path: string) =>
    path.endsWith("/runs") ? { runs: [] } : { token: "token", rows },
  );
  await act(async () =>
    root.render(<Standardize disabled={false} onDenied={() => {}} />),
  );
  const details = host.querySelector("details")!;
  await act(async () => {
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
  await click("Preview all nickname changes");
  expect(
    host.querySelector<HTMLInputElement>("input[type=checkbox]")!.checked,
  ).toBe(false);
  expect(host.textContent).toContain("Needs review");
  expect(host.textContent).toContain("Bob | Co-Leader | GMT-5");
});
it("stops a run, lists named skipped outcomes and never resumes terminal polling", async () => {
  vi.useFakeTimers();
  let stopped = false;
  transport.mockImplementation(async (path: string, method = "GET") => {
    if (path.endsWith("/runs"))
      return { runs: [{ run_id: "run", state: "queued" }] };
    if (path.endsWith("/stop")) {
      expect(method).toBe("POST");
      stopped = true;
      return { run_id: "run", state: "stopped" };
    }
    return {
      run_id: "run",
      state: stopped ? "stopped" : "queued",
      rows: [
        {
          discord_id: uid,
          name: "Ada",
          old_nickname: "Old",
          new_nickname: "New",
          revision: 1,
          status: "done",
          message: "Changed",
        },
        {
          discord_id: "234567890123456789",
          name: "Skipped member",
          revision: 1,
          status: "skipped",
          message: "Above bot",
        },
        {
          discord_id: "345678901234567890",
          name: "Waiting member",
          revision: 1,
          status: stopped ? "stopped" : "waiting",
          message: stopped ? "Stopped before this member started." : "Waiting",
        },
      ],
    };
  });
  await act(async () =>
    root.render(<Standardize disabled={false} onDenied={() => {}} />),
  );
  await act(async () => host.querySelector("summary")!.click());
  await act(async () => {
    const select = host.querySelector("select")!;
    select.value = "run";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const stop = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === "Stop run",
  )!;
  await act(async () => stop.click());
  expect(host.textContent).toContain("Stopped");
  expect(host.textContent).toContain("Skipped member");
  expect(host.textContent).toContain("Above bot");
  expect(host.textContent).toContain("Waiting member");
  expect(host.textContent).toContain("Stopped before this member started.");
  const count = transport.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(transport.mock.calls).toHaveLength(count);
  expect(
    [...host.querySelectorAll("button")].some(
      (b) => b.textContent === "Stop run",
    ),
  ).toBe(false);
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
  await click("Import nickname time zones");
  await click("Import nickname time zones");
  expect(posts[2].path).toContain("/import");
  expect(posts[2].body.request_id).not.toBe(posts[3].body.request_id);
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
it("retains the selected run and progress when editing a member and returning", async () => {
  transport.mockImplementation(async (path: string) => {
    if (path.endsWith("/runs"))
      return { runs: [{ run_id: "run", state: "queued" }] };
    if (path.endsWith("/runs/run"))
      return {
        run_id: "run",
        state: "queued",
        started_by: "Staff fixture",
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
  const details = [...host.querySelectorAll("details")].find(
    (d) => d.querySelector("summary")?.textContent === "Standardize nicknames",
  )!;
  await act(async () => {
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
  await act(async () => {
    const select = details.querySelector("select")!;
    select.value = "run";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(details.textContent).toContain("Standardize progress");
  await click("Edit Ada");
  await click("Cancel");
  expect(host.querySelector(".mt-top-actions")?.textContent).toContain(
    "Started by Staff fixture",
  );
  expect(host.querySelector(".mt-top-actions")?.textContent).toContain(
    "Standardize progress",
  );
});
it("unselects the whole preview and filters Needs review without changing selection", async () => {
  transport.mockImplementation(async (path: string) =>
    path.endsWith("/runs")
      ? { runs: [] }
      : {
          token: "fixture",
          rows: [
            {
              discord_id: uid,
              name: "Known",
              old_nickname: "Old",
              new_nickname: "New",
              revision: 1,
            },
            {
              discord_id: "234567890123456789",
              name: "Unknown",
              old_nickname: "Old",
              new_nickname: "New",
              revision: 1,
              needs_review: true,
            },
          ],
        },
  );
  await act(async () =>
    root.render(<Standardize disabled={false} onDenied={() => {}} />),
  );
  const details = host.querySelector("details")!;
  await act(async () => {
    details.open = true;
    details.dispatchEvent(new Event("toggle"));
  });
  await click("Preview all nickname changes");
  await act(async () =>
    host
      .querySelector<HTMLInputElement>(".mt-standardize-actions input")!
      .click(),
  );
  expect(host.querySelectorAll(".mt-list li")).toHaveLength(1);
  expect(host.querySelector(".mt-list")?.textContent).toContain("Unknown");
  await click("Unselect all");
  expect(
    [...host.querySelectorAll<HTMLButtonElement>("button")].find(
      (b) => b.textContent === "Rename 0 members",
    )?.disabled,
  ).toBe(true);
});

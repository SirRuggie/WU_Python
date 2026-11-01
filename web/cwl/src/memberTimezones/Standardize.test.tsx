// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
const transport = vi.hoisted(() => vi.fn());
vi.mock("../api", async (orig) => ({
  ...(await orig<object>()),
  api: transport,
}));
import Standardize from "./Standardize";
import type { Change } from "./types";
const uid = (i: number) => String(123456789012340000n + BigInt(i));
const rows: Change[] = Array.from({ length: 51 }, (_, i) => ({
  discord_id: uid(i),
  name: `Member ${i}`,
  old_nickname: `Member ${i} | EST 🇺🇸`,
  new_nickname: `Member ${i} | GMT-5 🇺🇸`,
  revision: 3,
  category: "will_change",
}));
rows.push({
  discord_id: uid(90),
  name: "Check member",
  old_nickname: "Bob | Co-Leader",
  new_nickname: "Bob | Co-Leader | GMT-5 🇺🇸",
  revision: 3,
  category: "check_name",
  needs_review: true,
});
rows.push({
  discord_id: uid(91),
  name: "Missing flag",
  old_nickname: "Flag | EST",
  new_nickname: null,
  revision: 2,
  category: "needs_flag",
  skip_reason: "Choose a country flag",
});
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  transport.mockReset().mockImplementation(async (path: string) =>
    path.endsWith("/import")
      ? { request_id: "request", status: "done", status_url: "/receipt" }
      : path.endsWith("/preview")
        ? { token: "fresh-token", rows }
        : path.endsWith("/confirm")
          ? { run_id: "run" }
          : path.endsWith("/runs")
            ? {
                runs: [{ run_id: "run", state: "queued", started_by: uid(0) }],
              }
            : {
                run_id: "run",
                state: "done",
                rows: rows.map((r) => ({
                  ...r,
                  status: "uncertain",
                  message: "Check Discord before repeating",
                })),
              },
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});
async function mount() {
  await act(async () =>
    root.render(<Standardize disabled={false} onDenied={() => {}} />),
  );
}
async function click(text: string) {
  const b = [...host.querySelectorAll("button")].find(
    (b) =>
      b.textContent === text ||
      b.getAttribute("aria-label") === text ||
      b.textContent?.trim().startsWith(text + " "),
  );
  expect(b).toBeTruthy();
  await act(async () => b!.click());
}
it("imports before a fresh preview, defaults only safe changes, and never auto-confirms", async () => {
  await mount();
  expect(transport).not.toHaveBeenCalled();
  await click("Review nicknames");
  expect(transport.mock.calls.map((c) => c[0])).toEqual([
    "/manage/member-timezones/import",
    "/manage/member-timezones/preview",
  ]);
  expect(host.querySelectorAll(".mt-list li")).toHaveLength(25);
  expect(host.textContent).toContain("51 selected");
  await click("Check name");
  expect(
    host.querySelector<HTMLInputElement>("input[type=checkbox]")!.checked,
  ).toBe(false);
  expect(host.textContent).toContain(
    "Bob | Co-Leader → Bob | Co-Leader | GMT-5",
  );
});
it("keeps selection across pages, filters and search, and sends exactly the bar count including hidden selection", async () => {
  await mount();
  await click("Review nicknames");
  await click("Next review members");
  await act(async () =>
    host.querySelector<HTMLInputElement>("input[type=checkbox]")!.click(),
  );
  expect(host.textContent).toContain("50 selected");
  await click("Needs flag");
  expect(host.textContent).toContain("50 hidden");
  await click("50 hidden");
  expect(host.querySelectorAll(".mt-list li")).toHaveLength(25);
  const input = host.querySelector<HTMLInputElement>("input[type=search]")!;
  await act(async () => {
    input.value = "Member 0";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.textContent).toContain("50 selected");
  await click("Rename 50");
  const sent = transport.mock.calls.find((c) =>
    String(c[0]).endsWith("/confirm"),
  )![2];
  expect(sent.token).toBe("fresh-token");
  expect(sent.selected).toHaveLength(50);
  expect(sent.selected).not.toContain(uid(25));
  expect(sent.selected).not.toContain(uid(90));
  expect(sent.selected).not.toContain(uid(91));
  expect(host.textContent).toContain("Check manually");
  expect(
    [...host.querySelectorAll("button")].some((b) =>
      /retry/i.test(b.textContent || ""),
    ),
  ).toBe(false);
});
it("uncertain import shows one message and no preview, and explicit retry uses a fresh request ID", async () => {
  transport.mockResolvedValue({
    request_id: "x",
    status: "uncertain",
    status_url: "/receipt",
  });
  await mount();
  await click("Review nicknames");
  expect(host.querySelectorAll("[role=alert]")).toHaveLength(1);
  expect(host.textContent).toContain(
    "Import stopped early. No nicknames changed. Press Review nicknames again.",
  );
  expect(
    transport.mock.calls.some((c) => String(c[0]).endsWith("/preview")),
  ).toBe(false);
  await click("Review nicknames");
  expect(transport.mock.calls[0][2].request_id).not.toBe(
    transport.mock.calls[1][2].request_id,
  );
});
it("double tap queues one import and Back discards late preview without cancelling committed profile writes", async () => {
  let resolve!: (v: unknown) => void;
  transport.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  await mount();
  const b = host.querySelector("button")!;
  await act(async () => {
    b.click();
    b.click();
  });
  expect(transport).toHaveBeenCalledTimes(1);
  await click("Back to members");
  await act(async () =>
    resolve({ status: "done", request_id: "x", status_url: "/receipt" }),
  );
  expect(transport).toHaveBeenCalledTimes(1);
  expect(host.querySelector('[aria-label="Nickname review"]')).toBeNull();
});
it("Past runs loads on demand, stops once and never offers replay of uncertain results", async () => {
  await mount();
  await click("Past runs");
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "run";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("Check manually");
  await click("Check manually");
  expect(host.textContent).toContain("Check Discord before repeating");
  expect(host.textContent).not.toContain(uid(0));
});

it("closing an in-flight import aborts the read but explicit retry retains its durable identity", async () => {
  const ids: string[] = [];
  let attempts = 0;
  transport.mockImplementation(
    (path: string, _method: string, body: any, options: any) => {
      if (path.endsWith("/import")) {
        ids.push(body.request_id);
        if (!attempts++) {
          return new Promise((_resolve, reject) =>
            options.signal.addEventListener(
              "abort",
              () => reject(new DOMException("Aborted", "AbortError")),
              { once: true },
            ),
          );
        }
        return Promise.resolve({
          status: "done",
          request_id: "x",
          status_url: "/receipt",
        });
      }
      return Promise.resolve({ token: "token", rows });
    },
  );
  await mount();
  await click("Review nicknames");
  await click("Back to members");
  await click("Review nicknames");
  expect(ids).toHaveLength(2);
  expect(ids[0]).toBe(ids[1]);
  expect(host.textContent).toContain("51 selected");
});
it("Stop uses the existing one-shot command and terminal polling never retries a nickname", async () => {
  let stopped = false;
  transport.mockImplementation(async (path: string) => {
    if (path.endsWith("/runs"))
      return { runs: [{ run_id: "run", state: "queued" }] };
    if (path.endsWith("/stop")) {
      stopped = true;
      return {};
    }
    return {
      run_id: "run",
      state: stopped ? "stopped" : "queued",
      rows: [
        {
          ...rows[0],
          status: stopped ? "stopped" : "waiting",
          message: "Stopped before this member started.",
        },
      ],
    };
  });
  await mount();
  await click("Past runs");
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "run";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await click("Stop run");
  expect(host.textContent).toContain("Stopped. 0 changed.");
  expect(
    transport.mock.calls.filter((c) => String(c[0]).endsWith("/stop")),
  ).toHaveLength(1);
  expect(host.textContent).toContain("Skipped");
});

it("Rename switches immediately to progress and a double tap sends one confirmation", async () => {
  let resolve!: (value: unknown) => void;
  const normal = transport.getMockImplementation()!;
  transport.mockImplementation((path: string, ...args: any[]) =>
    path.endsWith("/confirm")
      ? new Promise((r) => {
          resolve = r;
        })
      : normal(path, ...args),
  );
  await mount();
  await click("Review nicknames");
  const button = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === "Rename 51",
  )!;
  await act(async () => {
    button.click();
    button.click();
  });
  expect(
    transport.mock.calls.filter((c) => String(c[0]).endsWith("/confirm")),
  ).toHaveLength(1);
  expect(host.querySelector('[aria-label="Nickname review"]')).toBeNull();
  expect(host.textContent).toContain("Renaming 0 of 51");
  expect(host.querySelector("progress")?.max).toBe(51);
  await act(async () => resolve({ run_id: "run" }));
  expect(host.textContent).toContain("Done. 0 changed.");
});
it("running status polls each second and stops as soon as finished", async () => {
  vi.useFakeTimers();
  let reads = 0;
  transport.mockImplementation(async (path: string) =>
    path.endsWith("/runs")
      ? { runs: [{ run_id: "run", state: "queued" }] }
      : {
          run_id: "run",
          state: ++reads <= 2 ? "queued" : "done",
          rows: rows
            .slice(0, 2)
            .map((r) => ({ ...r, status: reads <= 2 ? "waiting" : "done" })),
        },
  );
  await mount();
  await click("Past runs");
  const select = host.querySelector("select")!;
  await act(async () => {
    select.value = "run";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("Renaming 0 of 2");
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000);
  });
  expect(host.textContent).toContain("Done. 2 changed.");
  const count = transport.mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10000);
  });
  expect(transport.mock.calls).toHaveLength(count);
});

it('keeps confirmed run and Stop when a subsequent read fails, then polling recovers on Changed', async () => {
  vi.useFakeTimers();
  const original=transport.getMockImplementation()!;
  let reads=0;
  transport.mockImplementation(async (...args: unknown[])=>{
    if(args[0]==='/manage/member-timezones/runs/run') {
      if(++reads===1) throw new Error('Temporary read failure');
      return {run_id:'run',state:'done',rows:[{...rows[0],status:'done'},{...rows[1],status:'uncertain'}]};
    }
    return original(...args);
  });
  await mount(); await click('Review nicknames'); await click('Rename');
  expect(host.textContent).toContain('Renaming');
  expect(host.textContent).toContain('Stop run');
  expect(host.textContent).not.toContain('Search nicknames');
  await act(async()=>vi.advanceTimersByTimeAsync(1000));
  expect(host.textContent).toContain('Done. 1 changed.');
  expect(host.textContent).toContain('Member 0');
  expect(host.textContent).not.toContain('Member 1 |');
});

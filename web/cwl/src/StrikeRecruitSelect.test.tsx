// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import StrikeRecruitSelect from "./StrikeRecruitSelect";
import { api } from "./api";
import type { ActivityAccount } from "./strikeActivityView";
import {
  openPicker,
  pickerByLabel,
  pickerValue,
  typeInPicker,
} from "./searchPickerTestUtils";

vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
const first = "241000000000000001",
  second = "241000000000000002";
const member = (id: string, name = "SHOGUN") => ({
  options: [
    { id, display_name: name, username: "fixture-shogun", avatar_url: null },
  ],
});
const queryMember = (id: string) => ({
  members: [
    {
      id,
      name: "SHOGUN",
      accounts: [],
      discord_profile: {
        id,
        display_name: "SHOGUN",
        username: "fixture-shogun",
        avatar_url: null,
      },
    },
  ],
});
let host: HTMLDivElement, root: Root;
let actDescriptor: PropertyDescriptor | undefined;
beforeEach(() => {
  actDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    "IS_REACT_ACT_ENVIRONMENT",
  );
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  vi.mocked(api)
    .mockReset()
    .mockImplementation(
      async (path) =>
        (path.startsWith("/strikes/members?query=")
          ? queryMember(first)
          : member(first)) as never,
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
  if (actDescriptor)
    Object.defineProperty(
      globalThis,
      "IS_REACT_ACT_ENVIRONMENT",
      actDescriptor,
    );
  else Reflect.deleteProperty(globalThis, "IS_REACT_ACT_ENVIRONMENT");
});
async function render(
  value = first,
  disabled = false,
  accounts: ActivityAccount[] = [],
) {
  await act(async () =>
    root.render(
      <StrikeRecruitSelect
        accounts={accounts}
        value={value}
        disabled={disabled}
        onChange={() => {}}
      />,
    ),
  );
}
const picker = () => pickerByLabel(host, "Member");
const idsCalls = () =>
  vi
    .mocked(api)
    .mock.calls.filter(([path]) => path.startsWith("/strikes/members?ids="));

it("hydrates a closed URL-selected recruit outside the family without opening or searching", async () => {
  await render();
  expect(pickerValue(picker())).toContain("SHOGUN");
  expect(pickerValue(picker())).toContain("fixture-shogun");
  expect(host.querySelector('[role="listbox"]')).toBeNull();
  expect(
    vi.mocked(api).mock.calls.map(([path, method]) => [path, method]),
  ).toEqual([[`/strikes/members?ids=${first}`, "GET"]]);
  await render();
  expect(idsCalls()).toHaveLength(1);
});

it("uses local family and search-result caches without duplicate selected-ID lookups", async () => {
  await render(first, false, [
    { discord_id: first, discord_name: "Family recruit" } as ActivityAccount,
  ]);
  expect(pickerValue(picker())).toContain("Family recruit");
  expect(api).not.toHaveBeenCalled();
  await render("");
  await openPicker(picker());
  await typeInPicker(picker(), "shogun");
  await act(async () => vi.advanceTimersByTimeAsync(250));
  await render(first);
  expect(pickerValue(picker())).toContain("SHOGUN");
  expect(idsCalls()).toHaveLength(0);
});

it("aborts changed and cleared selections and ignores responses even if fetch ignores Abort", async () => {
  const pending = new Map<string, (value: unknown) => void>();
  vi.mocked(api).mockImplementation(
    (path) => new Promise((resolve) => pending.set(path, resolve)) as never,
  );
  await render(first);
  const firstSignal = idsCalls()[0][3]?.signal;
  await render(second);
  expect(firstSignal?.aborted).toBe(true);
  await act(async () =>
    pending.get(`/strikes/members?ids=${second}`)!(
      member(second, "Second recruit"),
    ),
  );
  expect(pickerValue(picker())).toContain("Second recruit");
  await act(async () =>
    pending.get(`/strikes/members?ids=${first}`)!(
      member(first, "Late recruit"),
    ),
  );
  expect(pickerValue(picker())).not.toContain("Late recruit");
  await render(first);
  expect(idsCalls()).toHaveLength(3);
  const clearedSignal = idsCalls().at(-1)![3]?.signal;
  await render("");
  expect(clearedSignal?.aborted).toBe(true);
  await act(async () =>
    pending.get(`/strikes/members?ids=${first}`)!(
      member(first, "Late after clear"),
    ),
  );
  expect(pickerValue(picker())).toContain("Select a recruit");
  expect(host.textContent).not.toContain("Late after clear");
});

it("does not loop on empty or failed lookups, nor fetch disabled or invalid selections", async () => {
  vi.mocked(api).mockResolvedValue({ options: [] } as never);
  await render();
  await render();
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(idsCalls()).toHaveLength(1);
  expect(pickerValue(picker())).toContain("Selected member unavailable");
  vi.mocked(api).mockRejectedValue(new Error("Fixture offline"));
  await render(second);
  await render(second);
  expect(idsCalls()).toHaveLength(2);
  await render(first, true);
  await render("invalid");
  await render("");
  expect(idsCalls()).toHaveLength(2);
});

it("aborts on disable and unmount and never caches the ignored late selection", async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }) as never,
  );
  await render();
  const signal = idsCalls()[0][3]?.signal;
  await render(first, true);
  expect(signal?.aborted).toBe(true);
  await act(async () => resolve(member(first, "Late disabled")));
  expect(pickerValue(picker())).not.toContain("Late disabled");
  await render();
  expect(idsCalls()).toHaveLength(2);
  const unmountedSignal = idsCalls()[1][3]?.signal;
  await act(async () => root.unmount());
  expect(unmountedSignal?.aborted).toBe(true);
  root = createRoot(host);
});

it.each([
  queryMember(first),
  { options: "incomplete" },
  member(second, "Unrequested recruit"),
  { options: [{ id: "invalid", display_name: "Invalid identity" }] },
])(
  "rejects the wrong IDs envelope or identity without caching it (%j)",
  async (reply) => {
    vi.mocked(api).mockResolvedValue(reply as never);
    await render();
    expect(pickerValue(picker())).toContain("Selected member unavailable");
    expect(pickerValue(picker())).not.toContain("SHOGUN");
    expect(pickerValue(picker())).not.toContain("Unrequested recruit");
    await render();
    expect(idsCalls()).toHaveLength(1);
  },
);

it("uses the public identity-name fallback and never exposes a raw ID as the name", async () => {
  vi.mocked(api).mockResolvedValue({
    options: [
      {
        id: first,
        display_name: first,
        username: "username-only",
        avatar_url: null,
      },
    ],
  } as never);
  await render();
  expect(pickerValue(picker())).toContain("username-only");
  expect(pickerValue(picker())).not.toContain(first);
  vi.mocked(api).mockResolvedValue({
    options: [
      {
        id: second,
        display_name: second,
        username: second,
        avatar_url: null,
      },
    ],
  } as never);
  await render(second);
  expect(pickerValue(picker())).toContain("Unknown member");
  expect(pickerValue(picker())).not.toContain(second);
});

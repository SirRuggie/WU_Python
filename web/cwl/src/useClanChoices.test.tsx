import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

const hook = vi.hoisted(() => ({
  state: undefined as unknown,
  setter: vi.fn(),
  ref: { current: 0 },
  cleanup: undefined as (() => void) | undefined,
  value: undefined as unknown,
}));
const transport = vi.hoisted(() => vi.fn());
vi.mock("react", async (original) => {
  const actual = await original<typeof import("react")>();
  return {
    ...actual,
    useState: () => [hook.state, hook.setter],
    useRef: () => hook.ref,
    useEffect: (effect: () => void | (() => void)) => {
      hook.cleanup = effect() || undefined;
    },
  };
});
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
import { ApiError } from "./api";
import { useClanChoices } from "./useClanChoices";

type Choices = ReturnType<typeof useClanChoices>;
const channels = [{ id: "c1", name: "war-room", type: 0 }] as Choices["channels"];
const initial = {
  roles: [{ id: "r1", name: "War Team" }],
  channels,
  channelsReady: true,
  error: "",
};
function mount() {
  function Probe() {
    hook.value = useClanChoices();
    return null;
  }
  renderToStaticMarkup(<Probe />);
  return hook.value as Choices;
}
beforeEach(() => {
  hook.state = { ...initial };
  hook.setter.mockReset().mockImplementation((next: unknown) => {
    hook.state = typeof next === "function"
      ? (next as (current: unknown) => unknown)(hook.state)
      : next;
  });
  hook.ref = { current: 0 };
  hook.cleanup = undefined;
  hook.value = undefined;
  transport.mockReset();
});
afterEach(() => hook.cleanup?.());

it("clears channel and role choices after permission is denied", async () => {
  transport.mockRejectedValue(new ApiError("No access", 403));
  const { loadChoices } = mount();
  await loadChoices();
  expect(hook.state).toEqual({
    roles: [],
    channels: [],
    channelsReady: false,
    error: "No access",
  });
});

it("retains last-known choices on an ordinary outage", async () => {
  transport.mockRejectedValue(new ApiError("Service unavailable", 503));
  const { loadChoices } = mount();
  await loadChoices();
  expect(hook.state).toEqual({
    ...initial,
    channelsReady: false,
    error: "Service unavailable",
  });
});

it("ignores an older denied response after a newer lookup succeeds", async () => {
  let rejectOld!: (cause: unknown) => void;
  let resolveNew!: (value: unknown) => void;
  transport
    .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject; }))
    .mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));
  const { loadChoices } = mount();
  const oldRequest = loadChoices();
  const newRequest = loadChoices();
  expect(hook.state).toEqual({ ...initial, channelsReady: false });
  const fresh = {
    roles: [{ id: "r2", name: "New role" }],
    channels: [{ id: "c2", name: "new-room", type: 0 }],
  };
  resolveNew(fresh);
  await newRequest;
  rejectOld(new ApiError("No access", 403));
  await oldRequest;
  expect(hook.state).toEqual({ ...fresh, channelsReady: true, error: "" });
});

it("ignores a pending response after the hook unmounts", async () => {
  let reject!: (cause: unknown) => void;
  transport.mockImplementation(() => new Promise((_resolve, fail) => { reject = fail; }));
  const { loadChoices } = mount();
  const request = loadChoices();
  hook.setter.mockClear();
  hook.cleanup?.();
  hook.cleanup = undefined;
  reject(new ApiError("No access", 403));
  await request;
  expect(hook.setter).not.toHaveBeenCalled();
  expect(hook.state).toEqual({ ...initial, channelsReady: false });
});

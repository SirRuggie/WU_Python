// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import type { StaffDetailsRequest } from "./staffDetailsRequest";

const gate = vi.hoisted(() => {
  let resolve!: (value: unknown) => void;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
});
vi.mock("./StaffDetailsPanel", () => gate.promise);
import StaffDetailsHost from "./StaffDetailsHost";
import StaffPlayerButton from "./StaffPlayerButton";

let root: ReturnType<typeof createRoot> | undefined;
let host: HTMLDivElement;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  vi.restoreAllMocks();
});
it("queues Details before its lazy module resolves, opens the latest player exactly once, and retains Declaration read-only direct links", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/cwl/readiness?season=1");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const opened = vi.fn();
  await act(async () =>
    root!.render(
      <>
        <StaffDetailsHost />
        <StaffPlayerButton seasonId="1" tag="#PLAYERONE">
          Details one
        </StaffPlayerButton>
        <StaffPlayerButton seasonId="1" tag="#PLAYERTWO">
          Details two
        </StaffPlayerButton>
      </>,
    ),
  );
  await act(async () => host.querySelectorAll("button")[0].click());
  expect(host.textContent).toContain("Loading account details");
  expect(opened).not.toHaveBeenCalled();
  await act(async () => host.querySelectorAll("button")[1].click());
  await act(async () =>
    gate.resolve({
      default: function Panel({ request }: { request: StaffDetailsRequest }) {
        useEffect(() => {
          opened(request);
        }, []);
        return <div role="dialog">{request.tag}</div>;
      },
    }),
  );
  expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(1);
  expect(host.querySelector('[role="dialog"]')?.textContent).toBe("#PLAYERTWO");
  expect(opened).toHaveBeenCalledExactlyOnceWith(
    expect.objectContaining({ tag: "#PLAYERTWO" }),
  );
  await act(async () => root!.unmount());
  history.replaceState({}, "", "/cwl/readiness?season=1&account=%23DIRECT");
  root = createRoot(host);
  await act(async () => root!.render(<StaffDetailsHost />));
  expect(opened).toHaveBeenLastCalledWith(
    expect.objectContaining({
      tag: "#DIRECT",
      viewOnly: "declaration",
    }),
  );
});

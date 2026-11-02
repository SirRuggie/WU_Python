import DeclarationPingPanel from "./DeclarationPingPanel";
// @vitest-environment happy-dom
import { act, useEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import RosterFillerCheckbox from "./RosterFillerCheckbox";
import { FillerMarkQueue } from "./fillerMarkQueue";
import useFillerMarkQueue from "./useFillerMarkQueue";
import { api } from "./api";
let root: ReturnType<typeof createRoot> | undefined;
let host: HTMLDivElement;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
  vi.restoreAllMocks();
});
async function mount(node: React.ReactNode) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(node));
}
it("list and Details share immediate desired state and stay selectable while serial saves run", async () => {
  const releases: ((v: any) => void)[] = [];
  const wire = vi.fn(
    () => new Promise<any>((resolve) => releases.push(resolve)),
  );
  const q = new FillerMarkQueue("1", 9, wire);
  const changed = vi.fn();
  q.configure(changed, () => {});
  await mount(
    <>
      {["list-A", "list-B", "details-A"].map((area) => (
        <section key={area} data-area={area}>
          <RosterFillerCheckbox
            queue={q}
            seasonId="1"
            tag={area.includes("B") ? "#B" : "#A"}
            name={area.includes("B") ? "Bee" : "Aye"}
            value={false}
            markRevision={0}
            revision={9}
            onChanged={() => {
              throw Error("Queue must not separately refresh per control");
            }}
          />
        </section>
      ))}
    </>,
  );
  const box = (area: string) =>
    host.querySelector<HTMLInputElement>(`[data-area="${area}"] input`)!;
  await act(async () => box("list-A").click());
  expect(wire).toHaveBeenCalledTimes(1);
  expect(box("details-A").checked).toBe(true);
  expect(box("details-A").disabled).toBe(false);
  expect(box("list-B").disabled).toBe(false);
  await act(async () => {
    box("list-B").click();
    box("details-A").click();
  });
  expect(box("list-A").checked).toBe(false);
  expect(box("list-B").checked).toBe(true);
  expect(host.textContent).toContain("Saving…");
  expect(wire).toHaveBeenCalledTimes(1);
  await act(async () =>
    releases.shift()!({
      tag: "#A",
      revision: 10,
      roster_filler: true,
      mark_revision: 1,
    }),
  );
  expect(wire.mock.calls[1].slice(0, 3)).toEqual([
    "/seasons/1/roster-filler/%23B",
    "PATCH",
    { revision: 10, roster_filler: true, mark_revision: 0 },
  ]);
  expect(changed).not.toHaveBeenCalled();
  await act(async () =>
    releases.shift()!({
      tag: "#B",
      revision: 11,
      roster_filler: true,
      mark_revision: 1,
    }),
  );
  expect(wire.mock.calls[2].slice(0, 3)).toEqual([
    "/seasons/1/roster-filler/%23A",
    "PATCH",
    { revision: 11, roster_filler: false, mark_revision: 1 },
  ]);
  await act(async () =>
    releases.shift()!({
      tag: "#A",
      revision: 12,
      roster_filler: false,
      mark_revision: 2,
    }),
  );
  expect(changed).toHaveBeenCalledTimes(1);
  expect(box("list-A").checked).toBe(false);
  expect(box("details-A").checked).toBe(false);
  expect(host.textContent).not.toContain("Saving…");
  q.dispose();
});
it("page hook disposal stops queued work after unmount without waiting for an active request", async () => {
  let finish!: (value: any) => void;
  const wire = vi.spyOn(await import("./api"), "api").mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }) as ReturnType<typeof api>,
  );
  function Page() {
    const queue = useFillerMarkQueue("1");
    queue.syncRevision(9);
    return (
      <>
        {["#A", "#B"].map((tag) => (
          <RosterFillerCheckbox
            key={tag}
            queue={queue}
            seasonId="1"
            tag={tag}
            name={tag}
            value={false}
            markRevision={0}
            revision={9}
            onChanged={() => {}}
          />
        ))}
      </>
    );
  }
  await mount(<Page />);
  await act(async () => {
    host.querySelectorAll("input")[0].click();
    host.querySelectorAll("input")[1].click();
  });
  expect(wire).toHaveBeenCalledTimes(1);
  await act(async () => root!.unmount());
  root = undefined;
  await act(async () =>
    finish({ revision: 10, roster_filler: true, mark_revision: 1 }),
  );
  const callsAfterUnmount = wire.mock.calls.length;
  if (callsAfterUnmount > 1)
    await act(async () =>
      finish({ revision: 11, roster_filler: true, mark_revision: 1 }),
    );
  expect(callsAfterUnmount).toBe(1);
});
it("clears the page guard after unmount even when Ping cleanup runs before an active save settles", async () => {
  let finish!: (value: any) => void;
  const working = vi.fn();
  const wire = vi
    .spyOn(await import("./api"), "api")
    .mockImplementation((path: string) =>
      path.includes("/roster-filler/")
        ? (new Promise((resolve) => {
            finish = resolve;
          }) as ReturnType<typeof api>)
        : (Promise.resolve({
            revision: 0,
            channel: null,
            can_send: false,
            channels: [],
            active: null,
            test_running: false,
            history: [],
            cooldown_until: 0,
            test_channel: { id: "", name: "", revision: 0 },
          }) as ReturnType<typeof api>),
    );
  function Page() {
    const queue = useFillerMarkQueue("1");
    queue.syncRevision(9);
    useEffect(() => {
      working(queue.working);
    }, [queue.working]);
    useEffect(() => () => working(false), []);
    return (
      <>
        <RosterFillerCheckbox
          queue={queue}
          seasonId="1"
          tag="#A"
          name="A"
          value={false}
          markRevision={0}
          revision={9}
          onChanged={() => {}}
        />
        <DeclarationPingPanel
          seasonId="1"
          pool="lazy"
          missing={0}
          onWorking={(value) => working(value || queue.working)}
        />
      </>
    );
  }
  await mount(<Page />);
  await act(async () =>
    host
      .querySelector<HTMLInputElement>(".roster-filler-control input")!
      .click(),
  );
  expect(working).toHaveBeenLastCalledWith(true);
  await act(async () => root!.unmount());
  root = undefined;
  expect(working).toHaveBeenLastCalledWith(false);
  await act(async () =>
    finish({ revision: 10, roster_filler: true, mark_revision: 1 }),
  );
  expect(
    wire.mock.calls.filter((call) =>
      String(call[0]).includes("/roster-filler/"),
    ),
  ).toHaveLength(1);
  expect(working).toHaveBeenLastCalledWith(false);
});

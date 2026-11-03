// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import useConfirmDialog from "./useConfirmDialog";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const write = vi.fn();
function Example({ scope = "current" }: { scope?: string }) {
  const { confirm, dialog } = useConfirmDialog(scope);
  return (
    <>
      <button
        onClick={async () => {
          if (await confirm("Clear saved results?", "Clear results"))
            await write();
        }}
      >
        Clear
      </button>
      {dialog}
    </>
  );
}
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  write.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<Example />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const button = (name: string) =>
  [...document.querySelectorAll("button")].find((b) => b.textContent === name)!;
it("performs no write before confirm, cancel or Escape", async () => {
  await act(async () => button("Clear").click());
  expect(write).not.toHaveBeenCalled();
  await act(async () => button("Cancel").click());
  expect(write).not.toHaveBeenCalled();
  await act(async () => button("Clear").click());
  await act(async () =>
    document
      .querySelector("dialog")!
      .dispatchEvent(new Event("cancel", { cancelable: true })),
  );
  expect(write).not.toHaveBeenCalled();
  expect(document.querySelector("dialog")).toBeNull();
});
it("confirms exactly one write despite double opening and double confirmation", async () => {
  await act(async () => {
    button("Clear").click();
    button("Clear").click();
  });
  expect(document.querySelectorAll("dialog")).toHaveLength(1);
  await act(async () => {
    const submit = button("Clear results");
    submit.click();
    submit.click();
  });
  expect(write).toHaveBeenCalledTimes(1);
});
it("unmount cancels pending confirmation without writing", async () => {
  await act(async () => button("Clear").click());
  await act(async () => root.render(<div>Closed</div>));
  expect(write).not.toHaveBeenCalled();
  expect(document.querySelector("dialog")).toBeNull();
});
it("closing the confirmation after a request starts never retries it", async () => {
  let finish!: () => void;
  write.mockImplementation(
    () =>
      new Promise<void>((resolve) => {
        finish = resolve;
      }),
  );
  await act(async () => button("Clear").click());
  await act(async () => button("Clear results").click());
  await act(async () => root.render(<div>Closed</div>));
  await act(async () => finish());
  expect(write).toHaveBeenCalledTimes(1);
});

it("changing the request scope cancels rather than confirming a stale decision", async () => {
  await act(async () => button("Clear").click());
  await act(async () => root.render(<Example scope="other-season" />));
  expect(document.querySelector("dialog")).toBeNull();
  expect(write).not.toHaveBeenCalled();
  await act(async () => button("Clear").click());
  await act(async () => button("Clear results").click());
  expect(write).toHaveBeenCalledTimes(1);
});

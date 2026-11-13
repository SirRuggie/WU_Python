// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ImageCollection from "./ImageCollection";
import CommandImageLibrary from "./CommandImageLibrary";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const image = {
  url: "https://example.invalid/image.png",
  name: "Saved image",
  commands: [],
  folder: "General",
  archived: false,
  stored: true,
};
const button = (name: string) =>
  [...document.querySelectorAll("button")].find(
    (node) => node.textContent === name,
  )!;
async function click(name: string) {
  await act(async () => button(name).click());
}
async function change(
  input: HTMLInputElement | HTMLSelectElement,
  value: string,
) {
  await act(async () => {
    const prototype =
      input instanceof HTMLInputElement
        ? HTMLInputElement.prototype
        : HTMLSelectElement.prototype;
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(
      input,
      value,
    );
    input.dispatchEvent(
      new Event(input instanceof HTMLInputElement ? "input" : "change", {
        bubbles: true,
      }),
    );
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
async function dirty() {
  await click("Details");
  await change(
    document.querySelector<HTMLInputElement>(".gallery-edit input")!,
    "Unsaved name",
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
  transport
    .mockReset()
    .mockImplementation(async (_url, method) =>
      method ? { ...image, archived: true } : { images: [image] },
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<ImageCollection />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("Cancel and Escape keep the image draft and issue no mutation", async () => {
  await dirty();
  await click("Refresh gallery");
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Discard unsaved image details or pending uploads?",
  );
  expect(document.activeElement?.textContent).toBe("Cancel");
  await click("Cancel");
  expect(
    document.querySelector<HTMLInputElement>(".gallery-edit input")!.value,
  ).toBe("Unsaved name");
  await click("Refresh gallery");
  await act(async () =>
    document
      .querySelector(".confirm-dialog")!
      .dispatchEvent(new Event("cancel", { cancelable: true })),
  );
  expect(
    document.querySelector<HTMLInputElement>(".gallery-edit input")!.value,
  ).toBe("Unsaved name");
  expect(transport.mock.calls.filter((call) => call[1])).toEqual([]);
});
it("double archive and double confirm perform exactly one original request", async () => {
  await dirty();
  await act(async () => {
    button("Archive image").click();
    button("Archive image").click();
  });
  expect(document.querySelectorAll(".confirm-dialog")).toHaveLength(1);
  await act(async () => {
    const confirm = button("Discard changes");
    confirm.click();
    confirm.click();
  });
  expect(transport.mock.calls.filter((call) => call[1])).toEqual([
    [
      "/manage/text-command-images",
      "PATCH",
      {
        url: image.url,
        name: image.name,
        folder: image.folder,
        archived: true,
        expected: { name: image.name, folder: image.folder, archived: false },
      },
    ],
  ]);
});
it("Back cancels without losing draft and without forwarding the panel popstate", async () => {
  await dirty();
  await click("Refresh gallery");
  const app = vi.fn();
  window.addEventListener("popstate", app);
  await act(async () =>
    window.dispatchEvent(new PopStateEvent("popstate", { state: {} })),
  );
  expect(app).not.toHaveBeenCalled();
  window.removeEventListener("popstate", app);
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(
    document.querySelector<HTMLInputElement>(".gallery-edit input")!.value,
  ).toBe("Unsaved name");
  expect(transport).toHaveBeenCalledTimes(1);
});
it("async filter selection uses the event value after confirmation", async () => {
  await dirty();
  const filter = document.querySelectorAll<HTMLSelectElement>(
    ".gallery-filters select",
  )[1];
  await change(filter, "archived");
  expect(document.querySelector(".confirm-dialog")).not.toBeNull();
  await click("Discard changes");
  expect(filter.value).toBe("archived");
});
it("unmount cancels a pending request without writing or refreshing", async () => {
  await dirty();
  await click("Refresh gallery");
  await act(async () => root.render(<div>Another page</div>));
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(transport).toHaveBeenCalledTimes(1);
});
async function closeLibrary() {
  await act(async () =>
    document
      .querySelector<HTMLButtonElement>(
        ".command-image-library .action-panel-close",
      )!
      .click(),
  );
}
it("image library close awaits the guard and Cancel leaves it open", async () => {
  const close = vi.fn();
  await act(async () =>
    root.render(<CommandImageLibrary onClose={close} onChoose={vi.fn()} />),
  );
  await dirty();
  await closeLibrary();
  expect(close).not.toHaveBeenCalled();
  await click("Cancel");
  expect(close).not.toHaveBeenCalled();
  await closeLibrary();
  await click("Discard changes");
  expect(close).toHaveBeenCalledTimes(1);
});

// A small browser history: an entry stack, pushState, back() with popstate.
// With `later`, back() lands on a later task, as it does in a browser.
function fakeHistory(later = false) {
  const stack: unknown[] = [{}];
  let index = 0;
  vi.spyOn(history, "state", "get").mockImplementation(() => stack[index]);
  vi.spyOn(history, "pushState").mockImplementation((state) => {
    stack.splice(index + 1, stack.length, state);
    index = stack.length - 1;
  });
  vi.spyOn(history, "replaceState").mockImplementation((state) => {
    stack[index] = state;
  });
  const move = (delta: number) => {
    index = Math.max(0, Math.min(stack.length - 1, index + delta));
    window.dispatchEvent(
      new PopStateEvent("popstate", { state: stack[index] }),
    );
  };
  const go = (delta: number) =>
    later ? void setTimeout(() => move(delta), 5) : move(delta);
  vi.spyOn(history, "back").mockImplementation(() => go(-1));
  vi.spyOn(history, "go").mockImplementation((delta = 0) => go(delta));
  // Entries behind and at the current one; forward entries do not matter.
  const markers = () =>
    stack.slice(0, index + 1).map((entry, at) => {
      const marker =
        (entry as { wuActionPanel?: string } | null)?.wuActionPanel || "route";
      const name = marker.startsWith("image-confirm")
        ? "confirm"
        : marker.startsWith("action-panel")
          ? "panel"
          : "route";
      return at === index ? `*${name}` : name;
    });
  return { back: () => go(-1), markers };
}

it.each([
  ["Back", "Cancel", false, ["route", "*panel"]],
  ["Back", "Discard changes", false, ["*route"]],
  ["Back", "Cancel", true, ["route", "*panel"]],
  ["Back", "Discard changes", true, ["*route"]],
  ["Close", "Cancel", true, ["route", "*panel"]],
  ["Close", "Discard changes", true, ["*route"]],
])(
  "%s on a dirty image library, then %s (late history: %s), leaves no extra history entries",
  async (how, choice, later, expected) => {
    const nav = fakeHistory(later);
    const close = vi.fn();
    const settle = async () => {
      for (let i = 0; i < 4; i++)
        await act(async () => {
          await new Promise((resolve) => setTimeout(resolve, 25));
        });
    };
    // The parent unmounts the picker as soon as it closes, like the editor.
    function Parent() {
      const [open, setOpen] = useState(true);
      return open ? (
        <CommandImageLibrary
          onClose={() => {
            close();
            setOpen(false);
          }}
          onChoose={vi.fn()}
        />
      ) : null;
    }
    await act(async () => root.render(<Parent />));
    expect(nav.markers()).toEqual(["route", "*panel"]);
    await dirty();
    if (how === "Back") await act(async () => nav.back());
    else await closeLibrary();
    await settle();
    expect(document.querySelector(".confirm-dialog")).not.toBeNull();
    expect(nav.markers()).toEqual(["route", "panel", "*confirm"]);
    await click(choice);
    await settle();
    if (choice === "Cancel") {
      expect(close).not.toHaveBeenCalled();
    } else {
      expect(close).toHaveBeenCalledTimes(1);
      expect(document.querySelector(".command-image-library")).toBeNull();
    }
    expect(nav.markers()).toEqual(expected);
  },
);

it("closing the tab keeps the native beforeunload guard", async () => {
  await dirty();
  const event = new Event("beforeunload", { cancelable: true });
  window.dispatchEvent(event);
  expect(event.defaultPrevented).toBe(true);
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(transport).toHaveBeenCalledTimes(1);
});

// @vitest-environment happy-dom
import { act, useRef } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  observePageHeading,
  pageBreadcrumb,
  usePageHeadingVisibility,
} from "./usePageHeadingVisibility";

class Intersections {
  static instances: Intersections[] = [];
  callback: IntersectionObserverCallback;
  options?: IntersectionObserverInit;
  observe = vi.fn();
  disconnect = vi.fn();
  constructor(
    callback: IntersectionObserverCallback,
    options?: IntersectionObserverInit,
  ) {
    this.callback = callback;
    this.options = options;
    Intersections.instances.push(this);
  }
  emit(target: Element, visible: boolean) {
    this.callback(
      [{ target, isIntersecting: visible } as IntersectionObserverEntry],
      this as unknown as IntersectionObserver,
    );
  }
}
class Mutations {
  static instances: Mutations[] = [];
  callback: MutationCallback;
  observe = vi.fn();
  disconnect = vi.fn();
  constructor(callback: MutationCallback) {
    this.callback = callback;
    Mutations.instances.push(this);
  }
  emit() {
    this.callback([], this as unknown as MutationObserver);
  }
}
let main: HTMLElement, topbar: HTMLElement;
let stop: (() => void) | undefined;
let host: HTMLDivElement | undefined, root: Root | undefined;
const rectangle = (top: number, height: number, width = 300) =>
  ({
    top,
    bottom: top + height,
    left: 0,
    right: width,
    height,
    width,
    x: 0,
    y: top,
    toJSON() {},
  }) as DOMRect;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Intersections.instances = [];
  Mutations.instances = [];
  vi.stubGlobal("IntersectionObserver", Intersections);
  vi.stubGlobal("MutationObserver", Mutations);
  vi.stubGlobal("ResizeObserver", undefined);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      if (this.tagName === "HEADER") return rectangle(0, 64);
      if (this.tagName === "H1")
        return this.closest("[hidden]")
          ? rectangle(0, 0, 0)
          : rectangle(100, 30);
      return rectangle(0, 0, 0);
    },
  );
  topbar = document.createElement("header");
  main = document.createElement("main");
  document.body.append(topbar, main);
});
afterEach(async () => {
  stop?.();
  stop = undefined;
  if (root) await act(async () => root!.unmount());
  root = undefined;
  host?.remove();
  host = undefined;
  main.remove();
  topbar.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("omits duplicate group labels but keeps distinct context", () => {
  expect(pageBreadcrumb("Home", "Home")).toBe("");
  expect(pageBreadcrumb("Tickets", "Tickets")).toBe("");
  expect(pageBreadcrumb("CWL", "Build roster")).toBe("CWL");
  expect(pageBreadcrumb(undefined, "Dashboard")).toBe("");
});
it("starts with the real h1 visible, then follows it leaving and returning below the sticky bar", () => {
  main.innerHTML = "<h1>Tasks</h1>";
  const heading = main.querySelector("h1")!;
  const show = vi.fn();
  stop = observePageHeading(main, topbar, show);
  const observer = Intersections.instances[0];
  expect(show).toHaveBeenLastCalledWith(true);
  expect(observer.options).toEqual({
    rootMargin: "-64px 0px 0px 0px",
    threshold: 0,
  });
  observer.emit(heading, false);
  expect(show).toHaveBeenLastCalledWith(false);
  observer.emit(heading, true);
  expect(show).toHaveBeenLastCalledWith(true);
});
it("keeps topbar context on a loading or error page without h1 and binds a late heading", () => {
  main.innerHTML = '<p role="status">Loading</p>';
  const show = vi.fn();
  stop = observePageHeading(main, topbar, show);
  expect(show).toHaveBeenLastCalledWith(false);
  main.innerHTML = "<h1>Members</h1>";
  Mutations.instances[0].emit();
  expect(show).toHaveBeenLastCalledWith(true);
  expect(Intersections.instances).toHaveLength(1);
});
it("excludes hidden-page and dialog headings from the active page title", () => {
  main.innerHTML =
    '<section hidden><h1>Hidden page</h1></section><div role="dialog"><h1>Modal</h1></div><h1>Actual page</h1>';
  const show = vi.fn();
  stop = observePageHeading(main, topbar, show);
  expect(Intersections.instances[0].observe).toHaveBeenCalledWith(
    main.lastElementChild,
  );
});
it("rebinds a replaced heading and ignores the old observer's late delivery", () => {
  main.innerHTML = "<h1>Old page</h1>";
  const old = main.firstElementChild!;
  const show = vi.fn();
  stop = observePageHeading(main, topbar, show);
  const first = Intersections.instances[0];
  main.innerHTML = "<h1>New page</h1>";
  Mutations.instances[0].emit();
  expect(first.disconnect).toHaveBeenCalledOnce();
  expect(show).toHaveBeenLastCalledWith(true);
  first.emit(old, false);
  expect(show).toHaveBeenLastCalledWith(true);
  Intersections.instances[1].emit(main.firstElementChild!, false);
  expect(show).toHaveBeenLastCalledWith(false);
});
it("restores topbar context when the active heading disappears", () => {
  main.innerHTML = "<h1>Old page</h1>";
  const show = vi.fn();
  stop = observePageHeading(main, topbar, show);
  main.innerHTML = '<p role="alert">Page unavailable</p>';
  Mutations.instances[0].emit();
  expect(show).toHaveBeenLastCalledWith(false);
});
it("cleans up route observation and refuses late callbacks after cleanup", () => {
  main.innerHTML = "<h1>Tasks</h1>";
  const heading = main.firstElementChild!;
  const show = vi.fn();
  stop = observePageHeading(main, topbar, show);
  const observer = Intersections.instances[0];
  stop();
  stop = undefined;
  show.mockClear();
  observer.emit(heading, false);
  expect(show).not.toHaveBeenCalled();
  expect(observer.disconnect).toHaveBeenCalledOnce();
  expect(Mutations.instances[0].disconnect).toHaveBeenCalledOnce();
  main.innerHTML = "<h1>Late replacement</h1>";
  Mutations.instances[0].emit();
  expect(show).not.toHaveBeenCalled();
  expect(Intersections.instances).toHaveLength(1);
});
it("has a readable geometry fallback when IntersectionObserver is unavailable", () => {
  vi.stubGlobal("IntersectionObserver", undefined);
  main.innerHTML = "<h1>Tasks</h1>";
  const show = vi.fn();
  stop = observePageHeading(main, topbar, show);
  expect(show).toHaveBeenLastCalledWith(true);
});
function Harness({ route }: { route: string }) {
  const mainRef = useRef<HTMLElement>(null);
  const barRef = useRef<HTMLElement>(null);
  const visible = usePageHeadingVisibility(mainRef, barRef, route, true);
  return (
    <>
      <header ref={barRef}>
        <strong data-page-heading-visible={visible}>{route}</strong>
      </header>
      <main ref={mainRef}>
        <h1>{route}</h1>
      </main>
    </>
  );
}
it("the hook rebinds on navigation even when React reuses the h1 element", async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(<Harness route="Home" />));
  const old = Intersections.instances.at(-1)!;
  const h1 = host.querySelector("h1")!;
  await act(async () => old.emit(h1, false));
  expect(host.querySelector("strong")!.dataset.pageHeadingVisible).toBe(
    "false",
  );
  await act(async () => root!.render(<Harness route="Tasks" />));
  expect(host.querySelector("strong")!.dataset.pageHeadingVisible).toBe("true");
  await act(async () => old.emit(h1, false));
  expect(host.querySelector("strong")!.dataset.pageHeadingVisible).toBe("true");
});

// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import AccountMenu from "./AccountMenu";

let root: Root, host: HTMLDivElement;
const signOut = vi.fn();
const user = {
  id: "member-1",
  username: "chief",
  display_name: "Chief",
  avatar_url: null,
} as never;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() =>
    root.render(
      <>
        <div id="outside">Outside menu</div>
        <AccountMenu user={user} onSignOut={signOut} variant="profile" />
        <AccountMenu user={user} onSignOut={signOut} variant="avatar" />
      </>,
    ),
  );
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.clearAllMocks();
});

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        pointerType: "mouse",
        pointerId: 1,
        button: 0,
      }),
    );
    element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    element.dispatchEvent(
      new PointerEvent("pointerup", {
        bubbles: true,
        pointerType: "mouse",
        pointerId: 1,
        button: 0,
      }),
    );
    element.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
    (element as HTMLElement).click();
  });
}

it("shows a tappable profile row with identity and handle", () => {
  const trigger = host.querySelector<HTMLButtonElement>(
    ".account-menu-profile-trigger",
  );
  expect(trigger?.textContent).toContain("Chief");
  expect(trigger?.textContent).toContain("@chief");
  expect(trigger?.getAttribute("aria-haspopup")).toBe("true");
  expect(host.querySelector('button[aria-label="Sign out"]')).toBeNull();
});

it("opens Sign out from the profile menu and invokes the existing action", async () => {
  await click(host.querySelector(".account-menu-profile-trigger")!);
  const item = document.querySelector('[role="menuitem"]');
  expect(item?.textContent).toContain("Sign out");
  expect(document.querySelector('[role="separator"]')).not.toBeNull();
  await click(item!);
  expect(signOut).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});

it("closes on Escape and returns focus to the profile trigger", async () => {
  const trigger = host.querySelector<HTMLButtonElement>(
    ".account-menu-profile-trigger",
  )!;
  await click(trigger);
  const menu = document.querySelector('[role="menu"]')!;
  await act(async () => {
    menu.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

it("opens the same account actions from the mobile avatar button", async () => {
  const trigger = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Account menu"]',
  )!;
  expect(trigger.classList.contains("account-menu-avatar-trigger")).toBe(true);
  await click(trigger);
  expect(document.querySelector('[role="menu"]')).not.toBeNull();
  expect(document.querySelector('[role="menuitem"]')?.textContent).toContain(
    "Sign out",
  );
});

it("closes on an outside interaction", async () => {
  await click(host.querySelector(".account-menu-profile-trigger")!);
  expect(document.querySelector('[role="menu"]')).not.toBeNull();
  await click(host.querySelector("#outside")!);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});

it("disables the account trigger and sign-out action while pending", async () => {
  await act(async () =>
    root.render(
      <AccountMenu
        user={user}
        onSignOut={signOut}
        variant="profile"
        disabled
      />,
    ),
  );
  const trigger = host.querySelector<HTMLButtonElement>(
    ".account-menu-profile-trigger",
  )!;
  expect(trigger.disabled).toBe(true);
  await click(trigger);
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(signOut).not.toHaveBeenCalled();
});

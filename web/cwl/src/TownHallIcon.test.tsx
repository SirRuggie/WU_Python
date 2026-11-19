// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";

vi.mock("./api", () => ({ api: vi.fn() }));
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  vi.resetModules();
  vi.mocked(api).mockReset();
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("shares one read across many icons and shows loaded images", async () => {
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  const { default: Icon } = await import("./TownHallIcon");
  await act(async () =>
    root.render(
      <>
        <Icon level={19} />
        <Icon level={19} />
        <Icon level={12} />
      </>,
    ),
  );
  expect(host.textContent).toContain("TH 19");
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () =>
    finish([
      {
        level: 19,
        emoji_url:
          "https://cdn.discordapp.com/emojis/1571025137896005783.gif?size=64",
      },
    ]),
  );
  expect(host.querySelectorAll('img[alt="Town Hall 19"]')).toHaveLength(2);
  expect(host.textContent).toContain("TH 12");
  await act(async () => root.render(<Icon level={19} />));
  expect(api).toHaveBeenCalledTimes(1);
  expect(host.textContent).not.toContain("1571025137896005783");
});

it("keeps text for missing, malformed and failed images", async () => {
  vi.mocked(api).mockResolvedValue([
    {
      level: 19,
      emoji_url:
        "https://cdn.discordapp.com/emojis/1571025137896005783.webp?size=64",
    },
    { level: 18, emoji_url: "https://other.example/image.png" },
  ]);
  const { default: Icon } = await import("./TownHallIcon");
  await act(async () =>
    root.render(
      <>
        <Icon level={19} />
        <Icon level={18} />
        <Icon level={null} />
      </>,
    ),
  );
  expect(host.querySelectorAll("img")).toHaveLength(1);
  await act(async () =>
    host.querySelector("img")!.dispatchEvent(new Event("error")),
  );
  expect(host.querySelectorAll("img")).toHaveLength(0);
  expect(host.textContent).toContain("TH 19");
  expect(host.textContent).toContain("TH 18");
  expect(host.textContent).toContain("TH —");
});

it("retains plain text after a failed read without repeat requests", async () => {
  vi.mocked(api).mockRejectedValue(new Error("Unavailable"));
  const { default: Icon } = await import("./TownHallIcon");
  await act(async () => root.render(<Icon level={19} />));
  await act(async () =>
    root.render(
      <>
        <Icon level={19} />
        <Icon level={20} />
      </>,
    ),
  );
  expect(api).toHaveBeenCalledTimes(1);
  expect(host.querySelector("img")).toBeNull();
});

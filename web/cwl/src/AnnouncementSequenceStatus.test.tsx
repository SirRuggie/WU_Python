// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import AnnouncementSequenceStatus from "./AnnouncementSequenceStatus";
import type { ImageSequence } from "./manageBridge";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
let host: HTMLDivElement,
  root: ReturnType<typeof createRoot>,
  sequence: ImageSequence;
const refresh = vi.fn(async () => {});
const button = (text: string) =>
  [...document.querySelectorAll("button")]
    .reverse()
    .find((button) => button.textContent === text)!;
async function mount(canSend = true, announcementSent = false) {
  await act(async () =>
    root.render(
      <AnnouncementSequenceStatus
        seasonId="1"
        pool="lazy"
        sequence={sequence}
        canSend={canSend}
        announcementSent={announcementSent}
        channelName="#lazy-cwl"
        onRefresh={refresh}
      />,
    ),
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.clearAllMocks();
  api.mockResolvedValue({});
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  sequence = {
    sequence_id: "sequence",
    status: "stopped",
    announcement_confirmed: true,
    version: 1,
    channel_id: "channel",
    error: null,
    clans: [
      {
        tag: "#AAA",
        name: "Lazy.128",
        pages: 1,
        status: "posted",
        request_id: "first",
      },
      {
        tag: "#BBB",
        name: "Lazy.127",
        pages: 2,
        status: "failed",
        request_id: "second",
      },
    ],
    closing: null,
  };
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("resumes a known failure once and names the stopping clan", async () => {
  await mount();
  expect(host.textContent).toContain("Stopped at Lazy.127");
  await act(async () => button("Resume").click());
  expect(api).not.toHaveBeenCalled();
  expect(document.querySelector("dialog")?.textContent).toContain("Lazy.127");
  await act(async () => {
    button("Resume").click();
    button("Resume").click();
  });
  expect(api).toHaveBeenCalledTimes(1);
  expect(api).toHaveBeenCalledWith(
    "/seasons/1/manage-bridge/lazy/sequence/resume",
    "POST",
    { sequence_id: "sequence" },
  );
  expect(refresh).toHaveBeenCalledTimes(1);
});
it("canceling check-first writes nothing; confirmation captures the uncertain receipt", async () => {
  sequence.clans[1].status = "uncertain";
  await mount();
  expect(button("Resume")).toBeUndefined();
  await act(async () => button("Check first").click());
  expect(document.body.textContent).toContain(
    "Posting again may create a duplicate",
  );
  await act(async () => button("Cancel").click());
  expect(api).not.toHaveBeenCalled();
  await act(async () => button("Check first").click());
  await act(async () => button("Post again anyway").click());
  expect(api).toHaveBeenCalledWith(
    "/seasons/1/manage-bridge/lazy/sequence/recover",
    "POST",
    { sequence_id: "sequence", request_id: "second", confirm_duplicate: true },
  );
});
it("permission loss closes the recovery dialog and removes write actions", async () => {
  sequence.clans[1].status = "uncertain";
  await mount();
  await act(async () => button("Check first").click());
  await mount(false);
  expect(document.querySelector("dialog[open]")).toBeNull();
  expect(button("Check first")).toBeUndefined();
  expect(api).not.toHaveBeenCalled();
});
it("a late response after unmount does not refresh another season", async () => {
  let finish!: (value: object) => void;
  api.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await mount();
  await act(async () => button("Resume").click());
  await act(async () => button("Resume").click());
  await act(async () => root.render(null));
  await act(async () => finish({}));
  expect(refresh).not.toHaveBeenCalled();
});

it("shows the confirmed deleted-closing repost label", async () => {
  sequence.status = "complete";
  sequence.closing = {
    request_id: "closing",
    status: "posted",
    error: "Reposted (old message was deleted)",
  };
  await mount();
  expect(host.textContent).toContain("Reposted (old message was deleted)");
  expect(api).not.toHaveBeenCalled();
});

it("requires an explicit no-ping review before continuing an unconfirmed sent announcement", async () => {
  sequence.announcement_confirmed = false;
  await mount(true, true);
  expect(host.textContent).toContain("Announcement shows as sent");
  await act(async () => button("Post clan images now").click());
  expect(api).not.toHaveBeenCalled();
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain(
    "#lazy-cwl: 2 clan images then the closing note · No pings",
  );
  expect(
    [...dialog.querySelectorAll("li")].map((node) => node.textContent),
  ).toEqual(["Lazy.128", "Lazy.127"]);
  await act(async () => button("Cancel").click());
  expect(api).not.toHaveBeenCalled();
  await act(async () => button("Post clan images now").click());
  const confirm = button("Post clan images now");
  await act(async () => {
    confirm.click();
    confirm.click();
  });
  expect(api).toHaveBeenCalledExactlyOnceWith(
    "/seasons/1/manage-bridge/lazy/sequence/assume",
    "POST",
    {
      sequence_id: "sequence",
      version: 1,
      channel_id: "channel",
      confirm_no_pings: true,
    },
  );
});

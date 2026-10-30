// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import ChannelCombobox from "./ChannelCombobox";
import ModerationPreviewCard from "./ModerationPreviewCard";
import ScheduleEditor from "./warReminders/ScheduleEditor";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
import MemberActivityHistory from "./MemberActivityHistory";
let root: Root | undefined, host: HTMLDivElement;
async function render(element: React.ReactNode) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(element));
}
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
  transport.mockReset();
});
it("keeps the phone keyboard guidance accessible and reveals it only for fine pointers", async () => {
  await render(
    <ChannelCombobox
      label="Channel"
      channels={[]}
      value=""
      disabled={false}
      onChange={() => {}}
      onResolve={() => {}}
    />,
  );
  const input = host.querySelector("input")!;
  expect(input.placeholder).toBe("Search channels and forum posts");
  const description = document.getElementById(
    input.getAttribute("aria-describedby")!,
  )!;
  expect(
    description.querySelector(".channel-keyboard-hint")?.textContent,
  ).toContain("Use arrow keys and Enter");
  const css = readFileSync("src/ChannelCombobox.css", "utf8");
  const [phone, fine] = css.split("@media (pointer: fine)");
  expect(phone).toContain("clip-path: inset(50%)");
  expect(phone).toContain("width: 1px");
  expect(phone).not.toMatch(/display:\s*none|visibility:\s*hidden/);
  expect(fine).toContain("clip-path: none");
});
it("offers only channel search in the non-forum reminder consumer", async () => {
  await render(
    <ScheduleEditor
      settings={{
        enabled: false,
        channel_id: "",
        war_started: false,
        minutes: [],
        audience: "remaining",
      }}
      channels={[]}
      disabled={false}
      onChange={() => {}}
    />,
  );
  const input = host.querySelector<HTMLInputElement>('[role="combobox"]')!;
  expect(input.placeholder).toBe("Search channels");
  expect(
    document.getElementById(input.getAttribute("aria-describedby")!)
      ?.textContent,
  ).not.toContain("forum");
});
it("shows escaped names and hover IDs in history, with quiet initials on an empty image", async () => {
  transport.mockResolvedValue({
    events: [
      {
        id: "sample",
        user_id: "123456789012345678",
        display_name: "<b>Member</b>",
        event_type: "kick",
        moderator_id: "987654321098765432",
        moderator_name: "<img src=x>Staff",
        occurred_at: "2026-10-30T00:00:00Z",
        avatar_url: "/api/cwl/manage/member-events/sample/avatar",
      },
    ],
    next_cursor: null,
  });
  await render(<MemberActivityHistory />);
  expect(host.textContent).toContain("<img src=x>Staff");
  expect(host.textContent).not.toContain("987654321098765432");
  expect(host.textContent).not.toContain("123456789012345678");
  expect(host.querySelector('[title="987654321098765432"]')).not.toBeNull();
  expect(host.querySelectorAll("img")).toHaveLength(1);
  await act(async () =>
    host.querySelector("img")!.dispatchEvent(new Event("error")),
  );
  expect(host.querySelector("img")).toBeNull();
  expect(host.querySelector(".member-activity-avatar")?.textContent).toBe("<");
  expect(host.querySelector('[role="alert"]')).toBeNull();
});
it("adapts both preview formats without showing raw member IDs", async () => {
  const id = "123456789012345678";
  const content = `Actor <@${id}> · ID ${id}`;
  await render(
    <>
      <ModerationPreviewCard
        names={{ [id]: "<b>Sample</b>" }}
        payload={{ components: [{ type: 10, content }] }}
      />
      <ModerationPreviewCard
        forum
        names={{ [id]: "Sample" }}
        payload={{
          embeds: [{ description: content, footer: { text: `ID ${id}` } }],
        }}
      />
    </>,
  );
  expect(host.textContent).toContain("<b>Sample</b>");
  expect(host.querySelector("b")).toBeNull();
  expect(host.textContent).not.toContain(id);
  expect(host.querySelector(`[title="${id}"]`)).not.toBeNull();
});

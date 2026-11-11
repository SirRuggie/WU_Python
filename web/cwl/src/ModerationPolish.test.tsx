// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
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
const openPicker = async () => {
  await act(async () =>
    host.querySelector<HTMLButtonElement>(".search-picker-trigger")!.click(),
  );
  return host.querySelector<HTMLInputElement>('input[role="combobox"]')!;
};
it("lets the channel picker be driven by arrow keys and Enter", async () => {
  const onChange = vi.fn();
  await render(
    <ChannelCombobox
      label="Channel"
      channels={[
        { id: "111111111111111111", name: "alpha", type: 0 },
        { id: "222222222222222222", name: "beta", type: 0 },
      ]}
      value=""
      disabled={false}
      onChange={onChange}
      onResolve={() => {}}
    />,
  );
  const input = await openPicker();
  expect(input.placeholder).toBe("Search channels and forum posts");
  const key = async (name: string) =>
    act(async () => {
      input.dispatchEvent(
        new KeyboardEvent("keydown", { key: name, bubbles: true }),
      );
    });
  await key("ArrowDown");
  await key("Enter");
  expect(onChange).toHaveBeenCalledWith("222222222222222222");
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
  const input = await openPicker();
  expect(input.placeholder).toBe("Search channels");
  expect(host.textContent).not.toContain("forum");
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
  expect(host.querySelector(".roster-discord-avatar")?.textContent).toBe("<");
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

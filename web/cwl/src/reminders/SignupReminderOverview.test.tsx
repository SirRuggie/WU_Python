// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import Overview, {
  targetCwlMonth,
  shortReminderTime,
} from "./SignupReminderOverview";
import type { Campaign } from "../reminderCampaign";
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
let root: Root;
let host: HTMLDivElement;
afterEach(() => {
  if (root) act(() => root.unmount());
  host?.remove();
});
function fixture() {
  const variant = {
    enabled: true,
    title: "",
    body: "",
    media_url: "",
    destination_channel_id: "shared",
    role_ids: ["role"],
    buttons: [],
  };
  return {
    paused: false,
    timezone: "UTC",
    signup_deadline: "",
    reminder_sequence: { enabled: false },
    messages: Object.fromEntries(
      Array.from({ length: 6 }, (_, index) => [
        `message${index}`,
        {
          enabled: true,
          label: `Message ${index}`,
          schedule: {},
          variants: { main: { ...variant }, lazy: { ...variant } },
        },
      ]),
    ),
  } as Campaign;
}
function render(campaign: Campaign, activated = true) {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const edit = vi.fn();
  act(() =>
    root.render(
      <Overview
        campaign={campaign}
        activated={activated}
        cycle="2026-11"
        schedule={[]}
        destination={(id) => `channel-${id}`}
        recipient={(ids) => ids.join(",")}
        onEdit={edit}
        onTiming={() => {}}
      />,
    ),
  );
  return edit;
}
describe("signup reminder overview", () => {
  it("labels the target CWL month, including year rollover without retiming", () => {
    expect(targetCwlMonth("2026-11")).toBe("December 2026");
    expect(targetCwlMonth("2026-12")).toBe("January 2027");
    expect(targetCwlMonth("2026-13")).toContain("unavailable");
    expect(shortReminderTime("invalid")).toBe("invalid");
  });
  it("shows six rows, common settings once per pool and routes every Edit exactly", () => {
    const edit = render(fixture());
    expect(host.querySelectorAll("article")).toHaveLength(6);
    expect(host.textContent?.match(/Destination:/g)).toHaveLength(2);
    const buttons = [...host.querySelectorAll("article button")];
    expect(buttons).toHaveLength(12);
    buttons.forEach((button, index) => {
      act(() =>
        button.dispatchEvent(new MouseEvent("click", { bubbles: true })),
      );
      expect(edit).toHaveBeenLastCalledWith(
        `message${Math.floor(index / 2)}`,
        index % 2 ? "lazy" : "main",
      );
    });
  });
  it("never hides differing destinations, roles or disabled messages", () => {
    const campaign = fixture();
    campaign.messages.message3.variants.lazy.destination_channel_id =
      "different";
    campaign.messages.message4.variants.main.role_ids = ["other"];
    campaign.messages.message5.variants.lazy.enabled = false;
    render(campaign);
    expect(host.textContent).toContain("channel-different");
    expect(host.textContent).toContain("Notify: other");
    expect(host.querySelectorAll("article")).toHaveLength(6);
    expect(
      host.querySelector('[aria-label="Message 5"]')?.textContent,
    ).toContain("Disabled");
  });
});

it("inactive campaign never labels a row On or an upcoming send", () => {
  render(fixture(), false);
  expect(host.textContent).not.toMatch(/\bOn\b/);
  expect(host.textContent).not.toContain("No upcoming send");
});

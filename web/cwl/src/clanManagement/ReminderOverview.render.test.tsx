// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import ReminderOverview from "./ReminderOverview";
import { api } from "../api";
vi.mock("../api", () => ({ api: vi.fn(), ApiError: class extends Error {} }));
it("compacts off clans while keeping attention errors discoverable", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const row = {
    clan: { tag: "#AAA", name: "Quiet clan", type: "CWL" },
    settings: {
      enabled: false,
      channel_id: "",
      minutes: [],
      war_started: false,
      audience: "remaining",
    },
    health: { category: "off", label: "Off", detail: "" },
    checked_at: null,
    last_delivery: null,
  };
  vi.mocked(api).mockResolvedValue({
    clans: [
      row,
      {
        ...row,
        clan: { ...row.clan, tag: "#BBB", name: "Review clan" },
        health: {
          category: "attention",
          label: "Uncertain delivery",
          detail: "Check the channel before acting",
        },
      },
    ],
    generated_at: "",
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host),
    onOpen = vi.fn();
  try {
    await act(async () =>
      root.render(
        <ReminderOverview
          active
          channels={[]}
          channelsReady
          choicesError=""
          onRetryChoices={vi.fn()}
          onOpen={onOpen}
          returnTag={null}
          onAdd={vi.fn()}
        />,
      ),
    );
    expect(host.querySelectorAll(".overview-off-row")).toHaveLength(1);
    const compact = host.querySelector(".overview-off-row")!;
    expect(compact.textContent).toContain("Quiet clan");
    expect(compact.textContent).toContain("CWL · Off");
    expect(compact.textContent).not.toContain("No scheduled deliveries");
    expect(host.querySelector("tbody tr")!.textContent).toContain(
      "Review clan",
    );
    expect(host.textContent).toContain("Check the channel before acting");
    act(() => compact.querySelector<HTMLButtonElement>("button")!.click());
    expect(onOpen).toHaveBeenCalledWith(row.clan);
  } finally {
    act(() => root.unmount());
    host.remove();
  }
});

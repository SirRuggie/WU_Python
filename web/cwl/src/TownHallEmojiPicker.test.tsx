// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "./api";
import Picker, {
  matchesTownHall,
  suggestedTownHallEmoji,
  type TownHallEmoji,
} from "./TownHallEmojiPicker";
import {
  clearPicker,
  clickOption,
  openPicker,
  optionTexts,
  pickerByLabel,
  typeInPicker,
} from "./searchPickerTestUtils";

vi.mock("./api", () => ({ api: vi.fn() }));
const entries: TownHallEmoji[] = [
  {
    value: "<:TH_190:123456789012345670>",
    name: "TH_190",
    source: "bot",
    image_url:
      "https://cdn.discordapp.com/emojis/123456789012345670.webp?size=48",
    available: true,
  },
  {
    value: "<:TH_19A:123456789012345671>",
    name: "TH_19A",
    source: "server",
    image_url:
      "https://cdn.discordapp.com/emojis/123456789012345671.webp?size=48",
    available: false,
  },
  {
    value: "<a:TH_19A:123456789012345672>",
    name: "TH_19A",
    source: "bot",
    image_url:
      "https://cdn.discordapp.com/emojis/123456789012345672.gif?size=48",
    available: true,
  },
  {
    value: "<:TH_20:123456789012345673>",
    name: "TH_20",
    source: "bot",
    image_url:
      "https://cdn.discordapp.com/emojis/123456789012345673.webp?size=48",
    available: true,
  },
];
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
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

it("loads on first open, ranks this level, keeps sources and blocks unavailable emoji", async () => {
  vi.mocked(api).mockResolvedValue({ emojis: entries, errors: {} });
  const change = vi.fn();
  await act(async () =>
    root.render(<Picker value="" level={19} onChange={change} />),
  );
  expect(api).not.toHaveBeenCalled();
  const picker = pickerByLabel(host, "Town Hall emoji");
  await openPicker(picker);
  const rows = optionTexts(picker);
  expect(rows[0]).toContain("TH_19A");
  expect(rows[0]).toContain("Server emoji");
  expect(rows[1]).toContain("Bot emoji");
  const unavailable = picker.querySelector<HTMLElement>(
    '[role="option"][aria-disabled="true"]',
  )!;
  await act(async () => unavailable.click());
  expect(change).not.toHaveBeenCalled();
  await clickOption(picker, "Bot emoji");
  expect(change).toHaveBeenCalledWith(entries[2].value);
  expect(host.textContent).not.toContain("123456789012345672");
  expect(host.textContent).not.toContain("<:");
});

it("keeps saved names visible, clears exact markup and disables read-only selection", async () => {
  const change = vi.fn();
  await act(async () =>
    root.render(
      <Picker value={entries[2].value} level={19} onChange={change} disabled />,
    ),
  );
  expect(host.textContent).toContain("TH_19A");
  expect(host.textContent).not.toContain("Emoji no longer available");
  expect(
    host.querySelector<HTMLButtonElement>(".search-picker-trigger")!.disabled,
  ).toBe(true);
  await act(async () =>
    root.render(
      <Picker value={entries[2].value} level={19} onChange={change} />,
    ),
  );
  await clearPicker(pickerByLabel(host, "Town Hall emoji"));
  expect(change).toHaveBeenCalledWith("");
});

it("retries a 503 on the next open and displays partial-source failure", async () => {
  vi.mocked(api)
    .mockRejectedValueOnce(new Error("503"))
    .mockResolvedValueOnce({
      emojis: entries.slice(2),
      errors: { server: "Server emojis could not load." },
    });
  await act(async () =>
    root.render(<Picker value="" level={19} onChange={vi.fn()} />),
  );
  const picker = pickerByLabel(host, "Town Hall emoji");
  await openPicker(picker);
  expect(host.textContent).toContain("Emojis could not load. Try again.");
  await act(async () =>
    picker.querySelector<HTMLButtonElement>(".search-picker-trigger")!.click(),
  );
  await openPicker(picker);
  expect(api).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain("Server emojis could not load.");
  await typeInPicker(picker, "TH_20");
  expect(optionTexts(picker)).toHaveLength(1);
});

it("matches level boundaries and suggests only an exact available bot name", () => {
  for (const name of ["TH_19A", "TH19", "th_19w"])
    expect(matchesTownHall(name, 19)).toBe(true);
  for (const name of ["TH_1", "TH_190"])
    expect(matchesTownHall(name, 19)).toBe(false);
  expect(suggestedTownHallEmoji(entries, 20)).toBe(entries[3].value);
  expect(suggestedTownHallEmoji(entries, 19)).toBe(entries[2].value);
  expect(suggestedTownHallEmoji(entries, 21)).toBe("");
});

it("labels a missing saved emoji after lookup without exposing its markup", async () => {
  vi.mocked(api).mockResolvedValue({ emojis: [], errors: {} });
  await act(async () =>
    root.render(
      <Picker value={entries[2].value} level={19} onChange={vi.fn()} />,
    ),
  );
  await openPicker(pickerByLabel(host, "Town Hall emoji"));
  expect(host.textContent).toContain("TH_19A");
  expect(host.textContent).toContain("Emoji no longer available");
  expect(host.textContent).not.toContain("123456789012345672");
  expect(host.textContent).not.toContain("<a:");
});

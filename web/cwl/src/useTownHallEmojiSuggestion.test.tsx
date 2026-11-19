// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { api } from "./api";
import useSuggestion from "./useTownHallEmojiSuggestion";
vi.mock("./api", () => ({ api: vi.fn() }));

it("preselects, reruns for level changes, clears only auto choices and preserves manual choices", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.mocked(api).mockResolvedValue({
    emojis: [
      {
        value: "<:TH_20:123456789012345678>",
        name: "TH_20",
        source: "bot",
        available: true,
      },
      {
        value: "<:TH_21A:123456789012345679>",
        name: "TH_21A",
        source: "bot",
        available: true,
      },
    ],
    errors: {},
  });
  let pick!: (value: string) => void;
  let setLevel!: (value: number) => void;
  function Sample() {
    const [level, changeLevel] = useState(20);
    const [value, changeValue] = useState("");
    const suggestion = useSuggestion(level, changeValue);
    pick = suggestion.choose;
    setLevel = changeLevel;
    return (
      <output data-value={value}>
        {suggestion.suggestion
          ? "Found a bot emoji for this level. Save to confirm it."
          : "No automatic selection"}
      </output>
    );
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<Sample />));
    expect(host.querySelector("output")!.dataset.value).toBe(
      "<:TH_20:123456789012345678>",
    );
    expect(host.textContent).toContain("Save to confirm it.");
    await act(async () => setLevel(21));
    expect(host.querySelector("output")!.dataset.value).toBe(
      "<:TH_21A:123456789012345679>",
    );
    await act(async () => setLevel(22));
    expect(host.querySelector("output")!.dataset.value).toBe("");
    await act(async () => pick("<:Chosen:123456789012345680>"));
    await act(async () => setLevel(20));
    expect(host.querySelector("output")!.dataset.value).toBe(
      "<:Chosen:123456789012345680>",
    );
    expect(host.textContent).not.toContain("Save to confirm it.");
    await act(async () => pick(""));
    await act(async () => setLevel(21));
    expect(host.querySelector("output")!.dataset.value).toBe("");
    expect(api).toHaveBeenCalledTimes(1);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it.each(["success", "failure"])(
  "keeps a manual draft when the initial request has a late %s",
  async (outcome) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    let finish!: (value: unknown) => void, fail!: (reason: Error) => void;
    vi.mocked(api)
      .mockReset()
      .mockImplementation(
        () =>
          new Promise((resolve, reject) => {
            finish = resolve;
            fail = reject;
          }),
      );
    let choose!: (value: string) => void;
    function Sample() {
      const [value, setValue] = useState("");
      const suggestion = useSuggestion(20, setValue);
      choose = suggestion.choose;
      return <output data-value={value}>{suggestion.status}</output>;
    }
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () => root.render(<Sample />));
      await act(async () => choose("<:Manual:123456789012345680>"));
      await act(async () => {
        if (outcome === "failure") fail(new Error("503"));
        else
          finish({
            emojis: [
              {
                value: "<:TH_20:123456789012345678>",
                name: "TH_20",
                source: "bot",
                available: true,
              },
            ],
            errors: {},
          });
      });
      expect(host.querySelector("output")!.dataset.value).toBe(
        "<:Manual:123456789012345680>",
      );
      expect(api).toHaveBeenCalledTimes(1);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);

import { describe, expect, it } from "vitest";
import { compactRosterWeight } from "./rosterCompactWeight";

describe("compact roster weight", () => {
  it("shows whole and fractional thousands without a millions suffix", () => {
    expect(compactRosterWeight(172000)).toBe("172k");
    expect(compactRosterWeight(172500)).toBe("172.5k");
    expect(compactRosterWeight(1542000)).toBe("1542k");
  });

  it("keeps zero and unavailable weights distinct", () => {
    expect(compactRosterWeight(0)).toBe("0k");
    expect(compactRosterWeight(null)).toBe("—");
    expect(compactRosterWeight(Number.NaN)).toBe("—");
  });
});

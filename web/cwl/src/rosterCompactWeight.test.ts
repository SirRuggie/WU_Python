import { describe, expect, it, vi } from "vitest";
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

it("matches the original fixed formatter at rounding and range boundaries", () => {
  for (const weight of [
    null,
    NaN,
    Infinity,
    -Infinity,
    0,
    -0,
    49,
    50,
    51,
    949,
    950,
    951,
    1049,
    1050,
    1051,
    -50,
    -950,
    1542000,
    Number.MAX_SAFE_INTEGER,
  ]) {
    const expected =
      weight === null || !Number.isFinite(weight)
        ? "—"
        : `${new Intl.NumberFormat("en-US", { useGrouping: false, maximumFractionDigits: 1 }).format(weight / 1000)}k`;
    expect(compactRosterWeight(weight)).toBe(expected);
  }
});

it("does not construct another formatter while rendering repeated weights", () => {
  const NativeNumberFormat = Intl.NumberFormat;
  const construct = vi.spyOn(Intl, "NumberFormat").mockImplementation(function (locales, options) {
    return new NativeNumberFormat(locales, options);
  });
  try {
    for (let i = 0; i < 50; i++) compactRosterWeight(172000 + i * 100);
    expect(construct).not.toHaveBeenCalled();
  } finally {
    construct.mockRestore();
  }
});

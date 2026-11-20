import { expect, it } from "vitest";
import {
  identifierInputProps,
  mobileInputProps,
  numericInputProps,
  searchInputProps,
} from "./inputProps";

it("uses exact identifier text and the search keyboard action only for searches", () => {
  expect(identifierInputProps).toEqual({
    autoCapitalize: "none",
    autoCorrect: "off",
    spellCheck: false,
  });
  expect(searchInputProps).toEqual({
    ...identifierInputProps,
    enterKeyHint: "search",
  });
  expect(mobileInputProps("search")).toBe(searchInputProps);
  expect(mobileInputProps("number")).toBe(numericInputProps);
  expect(numericInputProps.inputMode).toBe("numeric");
  expect(mobileInputProps("text")).toEqual({});
  expect(mobileInputProps()).toEqual({});
});

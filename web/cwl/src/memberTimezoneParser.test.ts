import { describe, it, expect } from "vitest";
import { ownerTimeZone } from "./compareTimeZone";
import vectors from "../../../utils/member_timezone_vectors.json";

describe("shared nickname import/Compare vectors", () => {
  for (const [nickname, expected] of vectors) {
    it(String(nickname), () => {
      expect(ownerTimeZone(nickname as string)).toEqual(expected);
    });
  }
});

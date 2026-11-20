import { describe, expect, it } from "vitest";
import initial from "../../tests/fixtures/signup-reminders-data.json";
import { variantErrors } from "./reminderErrors";
import type { Campaign } from "../reminderCampaign";
const campaign = () => structuredClone(initial) as Campaign;
const ready = () => ({
  channels: {
    items: [{ id: "channel-main" }, { id: "channel-lazy" }],
    loading: false,
    error: "",
  },
  roles: {
    items: [{ id: "role-main" }, { id: "role-lazy" }],
    loading: false,
    error: "",
  },
});
describe("reminder send errors", () => {
  it.each([
    ["no_channel", "destination_channel_id", ""],
    ["unknown_channel", "destination_channel_id", "missing"],
    ["unknown_role", "role_ids", ["missing"]],
    ["empty_title", "title", "  "],
    ["empty_body", "body", "  "],
  ] as const)("identifies %s from the draft", (code, field, value) => {
    const draft = campaign();
    Object.assign(draft.messages.signup.variants.main, { [field]: value });
    expect(
      variantErrors(draft, "signup", "main", ready()).map(
        (error) => error.code,
      ),
    ).toEqual([code]);
    Object.assign(
      draft.messages.signup.variants.main,
      campaign().messages.signup.variants.main,
    );
    expect(variantErrors(draft, "signup", "main", ready())).toEqual([]);
  });
  it.each(["message", "pool"])("skips every error for Off %s", (kind) => {
    const draft = campaign();
    Object.assign(draft.messages.signup.variants.main, {
      title: "",
      body: "",
      destination_channel_id: "",
      role_ids: ["missing"],
    });
    if (kind === "message") draft.messages.signup.enabled = false;
    else draft.messages.signup.variants.main.enabled = false;
    expect(variantErrors(draft, "signup", "main", ready())).toEqual([]);
  });
  it.each(["loading", "failed"])(
    "does not invent unknown IDs when lookups are %s",
    (kind) => {
      const draft = campaign();
      Object.assign(draft.messages.signup.variants.main, {
        destination_channel_id: "unknown",
        role_ids: ["unknown"],
      });
      const lookups = ready();
      for (const lookup of [lookups.channels, lookups.roles]) {
        lookup.items = [];
        lookup.loading = kind === "loading";
        lookup.error = kind === "failed" ? "Unavailable" : "";
      }
      expect(variantErrors(draft, "signup", "main", lookups)).toEqual([]);
      draft.messages.signup.variants.main.destination_channel_id = "";
      expect(
        variantErrors(draft, "signup", "main", lookups).map(
          (error) => error.code,
        ),
      ).toEqual(["no_channel"]);
    },
  );
});

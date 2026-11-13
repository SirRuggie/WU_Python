import { api } from "../api";
import type { Campaign, CampaignState } from "../reminderCampaign";
import type { Act, Confirmation } from "./reminderWorkspaceHelpers";

export default function ReminderSaveBar({
  base,
  state,
  patch,
  body,
  dirty,
  preview,
  error,
  busy,
  disabled,
  act,
  load,
  setPreview,
  setNotice,
  setConfirmation,
}: {
  base: string;
  state: CampaignState;
  patch: Partial<Campaign>;
  body: {
    generation: string | null | undefined;
    patch: Partial<Campaign>;
    repeat_monthly: boolean;
  };
  dirty: boolean;
  preview: CampaignState | null;
  error: string;
  busy: boolean;
  disabled: boolean;
  act: Act;
  load: () => Promise<void>;
  setPreview: (preview: CampaignState | null) => void;
  setNotice: (notice: string) => void;
  setConfirmation: (confirmation: Confirmation | null) => void;
}) {
  return (
    <div
      className={`reminder-save ${dirty ? "has-changes" : ""}`}
      aria-busy={busy}
    >
      <span>
        {error ||
          (dirty
            ? preview
              ? "Review is ready. Save to use your changes."
              : "Unsaved changes"
            : "All changes saved")}
      </span>
      <div
        className="reminder-control-actions"
        role="group"
        aria-label="Review and save"
      >
        <button
          disabled={disabled || !dirty}
          onClick={() =>
            void act(async () => {
              setPreview(
                await api<CampaignState>(base + "/preview", "POST", body),
              );
              setNotice(
                "Preview ready. Review the schedule below before saving.",
              );
            })
          }
        >
          Preview schedule
        </button>
        <button
          className="primary"
          disabled={disabled || !dirty}
          onClick={() =>
            void act(async () => {
              const checked = await api<CampaignState>(
                base + "/preview",
                "POST",
                body,
              );
              setPreview(checked);
              setConfirmation({
                confirmLabel: "Save",
                text: "Save these reminder settings? They repeat monthly, and enabled messages will use the new times. Already-sent messages will not be sent again.",
                action: () =>
                  void act(async () => {
                    const result = await api<CampaignState>(base, "PATCH", {
                      ...body,
                      patch:
                        state?.campaign &&
                        !Object.hasOwn(state.campaign, "default_copy_version")
                          ? {
                              ...patch,
                              default_copy_version: 128,
                            }
                          : patch,
                    });
                    await load();
                    setNotice(
                      result.warning ||
                        "Saved. Signup links are unchanged. Scheduled sends are checked automatically.",
                    );
                  }),
              });
            })
          }
        >
          Save changes
        </button>
      </div>
    </div>
  );
}

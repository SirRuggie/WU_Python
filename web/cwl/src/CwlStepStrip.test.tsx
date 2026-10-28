import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { DashboardPermissions } from "./DashboardPermissions";
import CwlStepStrip from "./CwlStepStrip";
import type { PublicationDraft } from "./publication";
function markup(
  permissions: string[],
  draft: Partial<PublicationDraft> | null,
) {
  return renderToStaticMarkup(
    <DashboardPermissions.Provider value={{ owner: false, permissions }}>
      <CwlStepStrip
        step="review"
        draft={draft as PublicationDraft | null}
        onBuild={() => {}}
        onFinalize={() => {}}
        onAnnounce={() => {}}
      />
    </DashboardPermissions.Provider>,
  );
}
describe("CWL step strip", () => {
  it("shows changes, current publication and first draft distinctly", () => {
    expect(markup(["cwl"], { draft_changed: true })).toContain(
      'aria-label="Unpublished changes"',
    );
    expect(
      markup(["cwl"], {
        draft_changed: false,
        published: { version: 1 } as PublicationDraft["published"],
      }),
    ).toContain('aria-label="Published and current"');
    expect(
      markup(["cwl"], {
        published: null,
        last_publication: null,
        draft_changed: false,
        preview: { assigned_count: 125 } as PublicationDraft["preview"],
      }),
    ).toContain('aria-label="Unpublished changes"');
    expect(
      markup(["cwl"], {
        published: null,
        last_publication: null,
        draft_changed: false,
        preview: { assigned_count: 0 } as PublicationDraft["preview"],
      }),
    ).not.toContain('aria-label="Unpublished changes"');
    expect(markup(["cwl"], null)).not.toContain(
      'aria-label="Published and current"',
    );
    expect(markup(["cwl"], null)).toContain('aria-current="step"');
  });
  it("empty never-published seasons show neither status marker", () => {
    const html = markup(["cwl"], {
      published: null,
      last_publication: null,
      draft_changed: false,
      preview: { assigned_count: 0 } as PublicationDraft["preview"],
    });
    expect(html).not.toContain("Unpublished changes");
    expect(html).not.toContain("Published and current");
    expect(html).not.toContain("✓");
    expect(html).not.toContain("●");
  });
  it("respects independent build, publish and send permissions", () => {
    expect(markup(["cwl_send"], null)).toContain("3 Announce");
    expect(markup(["cwl_send"], null)).not.toContain("2 Finalize");
    expect(markup(["cwl_publish"], null)).not.toContain("1 Build");
    expect(markup(["cwl_signups"], null)).toContain("1 Build");
  });
});

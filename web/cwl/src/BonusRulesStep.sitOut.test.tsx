import { createRef } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import BonusRulesStep from "./BonusRulesStep";

it.each([2, 3, 0])(
  "shows the selected clan's %i-month sit-out rule",
  (months) => {
    const html = renderToStaticMarkup(
      <BonusRulesStep
        pool="lazy"
        sitOutMonths={months}
        lines={[]}
        fix={() => null}
        locked={false}
        minimum=""
        minimumInput={createRef()}
        minimumPreview={false}
        canSaveMinimum={false}
        onMinimum={() => {}}
        onSaveMinimum={() => {}}
        allowance={undefined}
        leagueMissing
        slots=""
        manualCount={false}
        countReady={false}
        countInput={createRef()}
        countDetails={createRef()}
        onSlots={() => {}}
        onManualCount={() => {}}
        accounts={[]}
        chipMinimum={null}
        meetsRule={0}
        listBusy={false}
        addCandidate={null}
      />,
    );
    expect(html).toContain(
      months === 0
        ? "No sit-out after a win"
        : `No bonus in the previous ${months} CWL months`,
    );
    expect(html).not.toContain("last 3 seasons");
  },
);

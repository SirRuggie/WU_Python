import { useCallback } from "react";
import useChoiceGroupScroll from "./useChoiceGroupScroll";
import { useHorizontalFades } from "./useHorizontalFades";
import "./horizontalFades.css";

/*
 * One horizontal tab or chip rail: reveals the selected item in its own
 * strip and fades the edge that has hidden items. Spread `fadeProps` on the
 * rail and add the `has-horizontal-fades` class.
 */
export default function useChoiceRail<T extends HTMLElement>(
  selection: string | number,
  revealSelection = true,
  externalRef?: (node: T | null) => void,
) {
  const fades = useHorizontalFades<T>();
  const fadeRef = fades.ref;
  const attach = useCallback(
    (node: T | null) => {
      fadeRef(node);
      externalRef?.(node);
    },
    [fadeRef, externalRef],
  );
  const ref = useChoiceGroupScroll<T>(selection, revealSelection, attach);
  return {
    ref,
    fadeProps: {
      "data-fade-left": fades.left,
      "data-fade-right": fades.right,
    },
  };
}

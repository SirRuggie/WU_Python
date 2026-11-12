import { createContext } from "react";

/** Native modal descendants must portal within the dialog's interactive tree. */
export const ActionPanelPortalContext = createContext<Element | undefined>(
  undefined,
);

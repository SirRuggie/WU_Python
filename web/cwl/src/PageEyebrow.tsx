import { createContext, useContext } from "react";

/** The sidebar group of the open page. App sets it from the sidebar data. */
export const PageGroupContext = createContext("");

/** The sidebar group for the eyebrow; empty when it only repeats the page name. */
export function pageGroup(section: string | undefined, label: string) {
  return section && section !== label ? section : "";
}

/**
 * The small gold label above a page title. It always names the sidebar group,
 * so the page and the menu cannot disagree. Pages never type their own text.
 */
export default function PageEyebrow() {
  const group = useContext(PageGroupContext);
  return group ? <p className="eyebrow page-eyebrow">{group}</p> : null;
}

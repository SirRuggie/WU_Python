/* Isolated compact-account UX checks, sharing the established fixture runner. */
process.env.WU_STRIKES_BROWSER = "strikes-usability.browser.cjs";
require("./run-strikes-layout.cjs");

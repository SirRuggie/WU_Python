/* The retired workspace now shares the activity-page fixture and entry. */
process.env.WU_STRIKES_BROWSER = "strikes-activity.browser.cjs";
require("./run-strikes-layout.cjs");

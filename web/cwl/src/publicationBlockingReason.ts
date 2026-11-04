/** Explain the first failed existing Publish gate without changing authorization. */
export function publicationBlockingReason(state: {
  hasDraft: boolean;
  canManage: boolean;
  locked: boolean;
  loading: boolean;
  hasError: boolean;
  archived: boolean;
  instructionsLength: number;
  changesReady: boolean;
  comparisonStatus?: "loading" | "ready" | "error";
  accounts: number;
  unplaced: number;
  acknowledged: boolean;
}): string {
  if (!state.hasDraft) return "Load the roster. Then publish.";
  if (!state.canManage)
    return "You do not have permission to publish this roster.";
  if (state.locked)
    return "Finish the current edit. Then publish.";
  if (state.loading) return "Wait for the roster refresh to finish.";
  if (state.hasError)
    return "Refresh the draft and fix the error. Then publish.";
  if (state.archived)
    return "You cannot publish an archived season.";
  if (state.instructionsLength > 2000)
    return "Joining instructions must not be more than 2,000 characters.";
  if (!state.changesReady)
    return state.comparisonStatus === "loading"
      ? ""
      : "Refresh the draft to load the latest roster changes.";
  if (!state.accounts) return "No signed-up accounts are in this roster yet.";
  if (state.unplaced > 0 && !state.acknowledged)
    return "Confirm that you know about the unplaced accounts. Then publish.";
  return "";
}

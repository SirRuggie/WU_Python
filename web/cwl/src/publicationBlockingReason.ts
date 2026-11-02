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
  accounts: number;
  unplaced: number;
  acknowledged: boolean;
}): string {
  if (!state.hasDraft) return "Load the roster before publishing.";
  if (!state.canManage)
    return "You do not have permission to publish this roster.";
  if (state.locked)
    return "Finish the current edit or operation before publishing.";
  if (state.loading) return "Wait for the roster refresh to finish.";
  if (state.hasError)
    return "Refresh the draft and resolve the error before publishing.";
  if (state.archived)
    return "Publishing is unavailable for an archived season.";
  if (state.instructionsLength > 2000)
    return "Joining instructions must be 2,000 characters or fewer.";
  if (!state.changesReady)
    return "Review the roster changes before publishing.";
  if (!state.accounts) return "No signed-up accounts are in this roster yet.";
  if (state.unplaced > 0 && !state.acknowledged)
    return "Acknowledge the unplaced accounts before publishing.";
  return "";
}

"""Read-only staff status words; never changes capture or eligibility data."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ParticipationEvidence:
    group_state: str | None = None
    group_current: bool = False
    active_wars_current: bool = False
    finalized_wars_usable: bool = False
    round_number: int | None = None
    failure_reason: str | None = None
    last_check_failed: bool = False


def effective_participation_status(stored_status, *, complete, has_results, evidence, sync_status=None,
                                   did_not_join=False):
    """Interpret existing evidence for display only.

    Callers must retain stored_status/complete for bonus and export decisions.
    Unknown evidence never establishes a successful check. The read adapter
    supplies freshness and confirmed-failure facts from the existing snapshot.
    """
    stored_status = stored_status or 'never'
    def result(code, label, *, warning=None, failed=False):
        status = {'code': code, 'label': label, 'warning': warning,
                  'failed_clan': failed, 'round': evidence.round_number}
        if (evidence.last_check_failed and not evidence.failure_reason
                and stored_status not in ('never', 'missing', 'unassigned', 'waiting', 'historical', 'season_mismatch')
                and sync_status != 'season_mismatch'):
            status['last_check_failed'] = True
        return status

    if sync_status == 'season_mismatch' or stored_status == 'season_mismatch':
        return result('season_mismatch', 'CWL month mismatch',
                      warning='The CWL month from Clash does not match this month.')
    if stored_status == 'waiting':
        return result('waiting', 'CWL has not started')
    if stored_status == 'historical':
        return result('historical', 'Saved history')
    if stored_status in ('never', 'missing', 'unassigned'):
        return result(stored_status, 'No assigned clan' if stored_status == 'unassigned' else 'Not checked')
    if did_not_join:
        # A final result for a finished CWL, never an incomplete one.
        return result('did_not_join', 'Did not join')
    if evidence.failure_reason:
        return result('stale' if has_results else 'unavailable', 'Last saved results' if has_results else 'Results unavailable',
                      warning='This clan could not refresh. Showing its last saved results.' if has_results
                      else 'This clan could not refresh. No saved results are available.', failed=True)
    if stored_status in ('unassigned', 'no_data', 'never', 'missing', 'unavailable'):
        labels = {'unassigned': 'No assigned clan', 'no_data': 'No CWL results',
                  'never': 'Not checked', 'missing': 'Not checked',
                  'unavailable': 'Results unavailable'}
        return result(stored_status, labels[stored_status])
    current = (evidence.group_current and evidence.active_wars_current
               and evidence.finalized_wars_usable)
    if current and evidence.group_state == 'PREPARATION':
        return result('preparation', 'CWL preparation')
    if current and evidence.group_state in ('WAR', 'INWAR'):
        return result('in_progress', 'CWL in progress')
    if current and evidence.group_state == 'ENDED':
        return (result('complete', 'Complete') if complete else
                result('incomplete', 'Incomplete', warning='Finished CWL results are incomplete.'))
    return result('not_recent', 'Results need a check',
                  warning='These results have not been checked recently.')

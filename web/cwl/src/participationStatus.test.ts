import { describe, expect, it } from 'vitest';
import { participationSummary, type ParticipationDisplayStatus } from './participation';
const status = (code: string, failed = false): ParticipationDisplayStatus => ({
  code, label: code === 'in_progress' ? 'CWL in progress' : 'Complete',
  warning: failed ? 'Could not refresh' : null, failed_clan: failed, round: 2,
});
describe('participation display summaries', () => {
  it('keeps normal progress neutral and counts the supplied scope', () => {
    const rows = [{ assigned_clan_tag: '#A', display_status: status('in_progress') }];
    expect(participationSummary(rows)).toEqual({ label: 'CWL in progress · round 2 of 7', warning: '', affected: 0, count: 1, updated: 1 });
  });
  it('names only failed clans in the displayed scope', () => {
    const rows = [
      { assigned_clan_tag: '#A', assigned_clan_name: 'Alpha', display_status: status('stale', true) },
      { assigned_clan_tag: '#B', assigned_clan_name: 'Beta', display_status: status('in_progress') },
      { assigned_clan_tag: '#C', assigned_clan_name: 'Gamma', display_status: status('stale', true) },
    ];
    const scoped = participationSummary(rows.filter(row => row.assigned_clan_tag !== '#C'));
    expect(scoped.warning).toBe('1 clan could not refresh: Alpha. Showing last saved results for 1 account in this view.');
    expect(scoped.warning).not.toContain('Gamma');
    expect(scoped.affected).toBe(1);
    expect(scoped.count).toBe(2);
    expect(scoped.updated).toBe(1);
  });
  it('counts saved and first-check failures separately within one named-clan line', () => {
    const rows = [
      { assigned_clan_tag: '#A', assigned_clan_name: 'Alpha', display_status: status('stale', true) },
      { assigned_clan_tag: '#A', assigned_clan_name: 'Alpha', display_status: status('unavailable', true) },
      { assigned_clan_tag: '#B', assigned_clan_name: 'Beta', display_status: status('unavailable', true) },
    ];
    expect(participationSummary(rows).warning).toBe('2 clans could not refresh: Alpha, Beta. Showing last saved results for 1 account in this view. No saved results yet for 2 accounts in this view.');
    expect(participationSummary(rows.slice(1)).warning).toBe('2 clans could not refresh: Alpha, Beta. No saved results yet for 2 accounts in this view.');
  });
  it('retains an older visible failure, but never borrows hidden-clan failures or repeats a fresh failure', () => {
    const sync = { status: 'stale', warning: 'Some Clash CWL data could not be refreshed; cached results are marked stale' };
    const old = { assigned_clan_tag: '#A', display_status: {
      ...status('not_recent'), warning: 'These results have not been checked recently.', last_check_failed: true,
    } };
    const healthy = { assigned_clan_tag: '#B', display_status: status('complete') };
    expect(participationSummary([old, healthy], sync).warning).toContain(sync.warning);
    expect(participationSummary([healthy], sync).warning).toBe('');
    expect(participationSummary([], sync).warning).toBe('');
    const fresh = { ...old, display_status: status('stale', true) };
    expect(participationSummary([fresh], sync).warning).not.toContain(sync.warning);
  });
});


describe('selected CWL month mismatch', () => {
  it.each([true, false])('keeps mismatch above saved/unchecked account status: %s', saved => {
    const rows = [{ assigned_clan_tag: '#A', assigned_clan_name: 'Alpha',
      display_status: status(saved ? 'stale' : 'never', saved) }];
    expect(participationSummary(rows, { status: 'season_mismatch', cycle: '2026-11' })).toEqual({
      label: 'CWL month mismatch', warning: 'Clash CWL month differs from the selected month',
      affected: 0, count: 1, updated: 0,
    });
  });
  it('treats Did not join and unassigned accounts as final, not incomplete', () => {
    const rows = [
      { assigned_clan_tag: '#A', display_status: status('complete') },
      { assigned_clan_tag: '#A', display_status: { ...status('did_not_join'), label: 'Did not join' } },
      { assigned_clan_tag: null, display_status: { ...status('unassigned'), label: 'No assigned clan' } },
    ];
    expect(participationSummary(rows)).toMatchObject({ label: 'CWL complete', warning: '' });
  });
});

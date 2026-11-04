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
});

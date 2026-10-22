import { describe, expect, it } from 'vitest';
import { bonusSelectionReason, bonusSelectionStatus, matchesExportSearch, rosterResultSummary } from './exportPreview';

describe('season export previews', () => {
  it('labels a voided bonus selection using its void reason', () => {
    const row = { player_name: 'Luke', tag: '#ABC', reason: 'Staff draw', voided_at: '2026-10-22', void_reason: 'Entered twice' };
    expect(bonusSelectionStatus(row)).toBe('Voided selection');
    expect(bonusSelectionReason(row)).toBe('Entered twice');
    expect(matchesExportSearch(row, 'entered twice', 'bonus-history')).toBe(true);
  });
  it('keeps results from another assignment out of roster preview totals', () => {
    expect(rosterResultSummary({ participation_matches_roster: false, participation_recorded_clan_name: 'Old Host' }, 'participation_')).toBe('Recorded for another assignment: Old Host');
    expect(rosterResultSummary({ matches_roster: true, attacks: 5, stars: 12 })).toBe('5 attacks · 12 stars');
  });
  it('labels an active saved selection without claiming a game award', () => {
    const row = { player_name: 'Lena', tag: '#XYZ', reason: 'Eligible', voided_at: null };
    expect(bonusSelectionStatus(row)).toBe('Saved selection');
    expect(bonusSelectionReason(row)).toBe('Eligible');
    expect(matchesExportSearch(row, 'lena')).toBe(true);
    expect(matchesExportSearch(row, '#xyz')).toBe(true);
    expect(matchesExportSearch(row, 'missing')).toBe(false);
    expect(matchesExportSearch(row, 'saved selection', 'accounts')).toBe(false);
  });
});

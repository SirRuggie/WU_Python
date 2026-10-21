import { expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import TaskEventTimer from './TaskEventTimer'
it('shows upcoming then live Clan Games timing at the exact boundary', () => {
  const before=renderToStaticMarkup(<TaskEventTimer kind="games" now={Date.UTC(2026,9,22,7,59)}/>);
  expect(before).toContain('Starts');
  expect(before).toContain('1 minute');
  expect(before).toContain('after the event starts');
  const started=renderToStaticMarkup(<TaskEventTimer kind="games" now={Date.UTC(2026,9,22,8)}/>);
  expect(started).toContain('Ends');
  expect(started).toContain('as activity is reported');
  const ended=renderToStaticMarkup(<TaskEventTimer kind="games" now={Date.UTC(2026,9,28,8)}/>);
  expect(ended).toContain('Next event');
  expect(ended).toContain('2026-11-22T08:00:00.000Z');
});
it('shows raid start and end timers using the Events calendar', () => {
  const upcoming=renderToStaticMarkup(<TaskEventTimer kind="raid" now={Date.UTC(2026,9,23,6)}/>);
  expect(upcoming).toContain('1 hour');
  const live=renderToStaticMarkup(<TaskEventTimer kind="raid" now={Date.UTC(2026,9,23,7)}/>);
  expect(live).toContain('Ends');
  expect(live).toContain('2026-10-26T07:00:00.000Z');
});
it('labels CWL signup timing separately from actual clan battles', () => {
  const upcoming=renderToStaticMarkup(<TaskEventTimer kind="cwl" now={Date.UTC(2026,9,21,12)}/>);
  expect(upcoming).toContain('Signup opens');
  expect(upcoming).toContain('2026-11-01T08:00:00.000Z');
  expect(upcoming).toContain('battle schedule is different');
  const open=renderToStaticMarkup(<TaskEventTimer kind="cwl" now={Date.UTC(2026,10,1,8)}/>);
  expect(open).toContain('Signup closes');
  expect(open).toContain('2026-11-03T08:00:00.000Z');
  const closed=renderToStaticMarkup(<TaskEventTimer kind="cwl" now={Date.UTC(2026,10,3,8)}/>);
  expect(closed).toContain('Next clan signup');
  expect(closed).toContain('2026-12-01T08:00:00.000Z');
});

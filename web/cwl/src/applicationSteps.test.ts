import { expect, it } from 'vitest'
import { applicationSteps } from './applicationSteps'
import type { ManagementSection } from './serverManagement'
const row = (
  id: string,
  extra: Partial<ManagementSection> = {},
): ManagementSection => ({
  id,
  label: id,
  description: '',
  group: 'Recruitment',
  allowed: true,
  ...extra,
})
it('keeps the applicant journey in order and testing last without unrelated or denied editors', () => {
  const groups = applicationSteps(
    [
      row('ticket_testing'),
      row('staff--main'),
      row('ticket_settings'),
      row('question--fwa'),
      row('gauntlet--apply'),
      row('roles'),
      row('publish--apply', { allowed: false }),
    ],
    '',
  )
  expect(groups.map((group) => group.title)).toEqual([
    'Application entry',
    'Applicant questions',
    'Staff responses',
    'Channels, access & timing',
    'Testing',
  ])
  expect(
    groups.flatMap((group) => group.items.map((item) => item.id)),
  ).toHaveLength(5)
})
it('searches visible descriptions and group names while retaining exact editor endpoints', () => {
  const item = row('question--main', {
    label: 'Main',
    description: 'Ask their player tag',
    endpoint: '/manage/questions/main',
  })
  expect(applicationSteps([item], 'PLAYER TAG')[0].items).toEqual([
    { ...item, group: 'Questions' },
  ])
  expect(
    applicationSteps([item], 'Applicant questions')[0].items[0].endpoint,
  ).toBe(item.endpoint)
  expect(applicationSteps([item], 'unmatched')).toEqual([])
})

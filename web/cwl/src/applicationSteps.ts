import type { ManagementSection } from './serverManagement'
import { areaSections } from './managementAreas'
const steps = [
  {
    id: 'Messages',
    title: 'Application entry',
    description: 'Apply messages and where applicants start.',
  },
  {
    id: 'Questions',
    title: 'Applicant questions',
    description: 'Questions asked during Main and FWA applications.',
  },
  {
    id: 'Staff messages',
    title: 'Staff responses',
    description: 'Messages used when reviewing an application.',
  },
  {
    id: 'Channels & access',
    title: 'Channels, access & timing',
    description: 'Ticket destinations, staff visibility and waiting periods.',
  },
  {
    id: 'Testing',
    title: 'Testing',
    description: 'Optional test tickets, separate from live applications.',
  },
]
export function applicationSteps(sections: ManagementSection[], query: string) {
  const needle = query.trim().toLocaleLowerCase()
  const allowed = areaSections(sections, 'applications-settings')
  return steps
    .map((step) => ({
      ...step,
      items: allowed.filter(
        (item) =>
          item.group === step.id &&
          (!needle ||
            `${step.title} ${item.label} ${item.description}`
              .toLocaleLowerCase()
              .includes(needle)),
      ),
    }))
    .filter((step) => step.items.length > 0)
}

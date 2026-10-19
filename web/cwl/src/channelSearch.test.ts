import { describe, expect, it } from 'vitest'
import { filterChannels } from './channelSearch'
const channels = [
  { id: '123456789012345678', name: 'main-cwl', type: 0 },
  { id: '987654321098765432', name: 'lazy-cwl', type: 5 },
  { id: '111111111111111111', name: 'general', type: 0 },
]
describe('Discord channel search', () => {
  it('matches partial names and IDs without requiring a leading hash', () => {
    expect(filterChannels(channels, 'CWL').map(channel => channel.name)).toEqual(['main-cwl', 'lazy-cwl'])
    expect(filterChannels(channels, '#lazy').map(channel => channel.id)).toEqual(['987654321098765432'])
    expect(filterChannels(channels, '567890').map(channel => channel.name)).toEqual(['main-cwl'])
  })
  it('keeps all channels available for an empty query', () => { expect(filterChannels(channels, '')).toEqual(channels) })
})

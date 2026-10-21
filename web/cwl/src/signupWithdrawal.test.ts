import {expect, it, vi} from 'vitest'
import {withdrawInOrder} from './signupWithdrawal'

it('stops on an uncertain failure without retrying or deleting later accounts', async () => {
  const error = new Error('Connection lost')
  const remove = vi.fn().mockResolvedValueOnce({ok:true}).mockRejectedValueOnce(error)
  const result = await withdrawInOrder(['#ONE','#TWO','#THREE'], remove)
  expect([...result.removed]).toEqual(['#ONE'])
  expect(result.error).toBe(error)
  expect(remove.mock.calls).toEqual([['#ONE'],['#TWO']])
})
it('confirms every successful withdrawal and avoids duplicate requests', async () => {
  const remove = vi.fn().mockResolvedValue({ok:true})
  const result = await withdrawInOrder(['#ONE','#TWO','#ONE'], remove)
  expect([...result.removed]).toEqual(['#ONE','#TWO'])
  expect(result.error).toBeNull()
  expect(remove).toHaveBeenCalledTimes(2)
})

import {expect, it, vi} from 'vitest'
import {saveSignupMoves} from './signupMoves'
import type {Signup} from './api'
const main: Signup = {tag:'#ONE', user_id:'1', pool:'main', prefer_crystal_1_or_lower:true}
const lazy: Signup = {...main, tag:'#TWO', pool:'lazy'}
it('saves both directions without changing source consent or preferences', async () => {
  const save = vi.fn().mockResolvedValue({ok:true})
  const result = await saveSignupMoves([{signup:main,destination:'lazy'},{signup:lazy,destination:'main'}], save)
  expect(save.mock.calls).toEqual([['main',[lazy]],['lazy',[main]]])
  expect(result).toEqual({saved:['#TWO','#ONE'],error:null})
})
it('retains pending changes after partial failure and never retries', async () => {
  const error = new Error('Unavailable')
  const save = vi.fn().mockResolvedValueOnce({ok:true}).mockRejectedValueOnce(error)
  const result = await saveSignupMoves([{signup:main,destination:'lazy'},{signup:lazy,destination:'main'}], save)
  expect(result).toEqual({saved:['#TWO'],error})
  expect(save).toHaveBeenCalledTimes(2)
})
it('stops after an uncertain first save and skips unchanged destinations', async () => {
  const save = vi.fn().mockRejectedValue(new Error('Unknown result'))
  const result = await saveSignupMoves([{signup:main,destination:'lazy'},{signup:lazy,destination:'main'}], save)
  expect(result.saved).toEqual([])
  expect(save).toHaveBeenCalledTimes(1)
  save.mockClear()
  expect(await saveSignupMoves([{signup:main,destination:'main'}],save)).toEqual({saved:[],error:null})
  expect(save).not.toHaveBeenCalled()
})

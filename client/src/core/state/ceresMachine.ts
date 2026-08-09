import { ceresReducer, initialCeresState } from './ceresReducer'
import type { CeresAction } from './ceresEvents'
import type { CeresState } from './ceresTypes'

export type CeresDispatch = (action: CeresAction) => void

export function reduceCeresState(state: CeresState = initialCeresState, action: CeresAction) {
  return ceresReducer(state, action)
}

export { initialCeresState }

import type { CeresState } from './ceresTypes'

export const selectOrbView = (state: CeresState) => ({
  orbState: state.orbState,
  visualIntensity: state.visualIntensity,
  audioAmplitude: state.audioAmplitude,
  entryEffect: state.entryEffect,
  stateEnteredAt: state.stateEnteredAt,
})

export const selectIsConnected = (state: CeresState) => state.connectionState === 'connected'

export const selectCanInterrupt = (state: CeresState) =>
  state.orbState === 'SPEAKING' || state.orbState === 'THINKING'

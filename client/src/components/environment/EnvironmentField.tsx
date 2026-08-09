import type { OrbState } from '../../core/state/ceresTypes'
import { SpatialLighting } from './SpatialLighting'
import { TopologyCanvas } from './TopologyCanvas'

export function EnvironmentField({ state, visualIntensity, audioAmplitude }: {
  state: OrbState
  visualIntensity: number
  audioAmplitude: number
}) {
  return (
    <>
      <div className="cosmic-grid" />
      <TopologyCanvas state={state} visualIntensity={visualIntensity} audioAmplitude={audioAmplitude} />
      <SpatialLighting state={state} visualIntensity={visualIntensity} audioAmplitude={audioAmplitude} />
    </>
  )
}

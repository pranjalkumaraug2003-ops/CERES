import type { OrbState } from '../../core/state/ceresTypes'

export function SpatialLighting({ state, visualIntensity, audioAmplitude }: {
  state: OrbState
  visualIntensity: number
  audioAmplitude: number
}) {
  return (
    <>
      <div
        className={`spatial-vignette state-${state.toLowerCase()}`}
        style={{ opacity: 0.62 + visualIntensity * 0.28 }}
      />
      <div
        className="spatial-aurora"
        style={{ opacity: 0.2 + visualIntensity * 0.34 + audioAmplitude * 0.18 }}
      />
    </>
  )
}
